#!/usr/bin/env python3
"""
HF22 Pulse Stall/Recovery 12-Hour Stress Test
==============================================
- 40 SNs, 20 unique operators (op1-op20, 2 SNs each)
- UNLOCK_DURATION = 30s = 6 blocks (compiled into testnet binary)
- HF22 fires at block 250: operator dedup activates
- Stall: deregister op11-op20 (10 operators) → 10 unique ops → confirmed stall
- Recovery phase 1: re-register op11 → 11 unique ops → Pulse resumes
- Recovery phase 2: re-register op12-op20 → 20 unique ops → full health
- Random Pulse run between cycles: 15-25 min (900-1500 blocks-worth of wall time)
- Full event log → JSON for post-run report

Usage:
  python3 hf22-12h-test.py [--duration-hours N] [--setup-only]
"""
import argparse, json, os, random, socket, subprocess, sys, time
import urllib.request, urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────
SEED_RPC    = "http://127.0.0.1:49001/json_rpc"
WALLET_RPC  = "http://127.0.0.1:18183/json_rpc"
WALLET_DIR  = "/home/svshearer/xeqm-testnet/wallet"
DATA_DIR    = "/home/svshearer/xeqm-testnet/data"
LOG_DIR     = "/home/svshearer/xeqm-testnet/logs"
XEQMD       = "/home/svshearer/xeqm-core/build/bin/xeqm-d"
XEQM_RPC   = "/home/svshearer/xeqm-core/build/bin/xeqm-rpc"

COIN              = 1_000_000_000
STAKING_AMT       = 100 * COIN          # 100 XEQM per SN
NUM_OPS           = 20                  # op1-op20
SNS_PER_OP        = 2                   # snode1/2=op1, snode3/4=op2, ...
TOTAL_SNS         = NUM_OPS * SNS_PER_OP  # 40
CORE_OPS          = 10                  # op1-op10 stay permanent (core fleet)
TRANSIENT_OPS_START = 11               # op11-op20 are stall/recovery operators
TRANSIENT_OPS_END   = 20
STALL_THRESHOLD   = 12                  # unique ops that cause stall (empirically confirmed)
PULSE_MIN         = 12                  # PULSE_MIN_SERVICE_NODES

SEED_P2P          = 49000
SEED_RPC_PORT     = 49001

GOV_ADDRESS  = "XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx"
GOV_VIEW_KEY = "8e34dd7f6eb9b9f28be81619e20765c53b79070aab49c353ffc877b67389cd09"
GOV_SPEND_KEY= "0c999a88be252215b48735272e5cf3dd86d54f850bb0bc8bfe9aea0de7549405"

UNLOCK_BLOCKS = 6   # 30s / 5s TARGET_BLOCK_TIME — unlock happens after this many blocks

# stall cycle: after N minutes of Pulse, induce next stall
STALL_INTERVAL_MIN_SECS = 900   # 15 min
STALL_INTERVAL_MAX_SECS = 1500  # 25 min

# ── State ─────────────────────────────────────────────────────────────────────
EVENT_LOG = []         # list of event dicts — written to JSON at end
BLOCK_LOG = []         # list of block dicts — every block
RUN_START = time.time()

def now_str():
    return datetime.now().strftime("%H:%M:%S")

def elapsed():
    return str(timedelta(seconds=int(time.time() - RUN_START)))

def log(msg, level="INFO"):
    ts = now_str()
    el = elapsed()
    print(f"[{ts} +{el}] {level}: {msg}", flush=True)

def event(kind, **kw):
    tip = height()
    e = {"kind": kind, "wall_time": now_str(), "elapsed_s": int(time.time()-RUN_START),
         "height": tip, **kw}
    EVENT_LOG.append(e)
    log(f"EVENT {kind}: {kw}", level="EVENT")

# ── RPC helpers ───────────────────────────────────────────────────────────────
def rpc(url, method, params=None, timeout=20):
    body = json.dumps({"jsonrpc":"2.0","method":method,
                       "params":params or {},"id":"0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    if "error" in d:
        raise RuntimeError(f"{method}: {d['error']['message']}")
    return d.get("result", {})

def seed(method, params=None, **kw):
    return rpc(SEED_RPC, method, params, **kw)

def wallet(method, params=None, **kw):
    return rpc(WALLET_RPC, method, params, **kw)

def snode_rpc(idx, method, params=None, **kw):
    port = 49000 + idx * 100 + 1
    return rpc(f"http://127.0.0.1:{port}/json_rpc", method, params, **kw)

def height():
    return seed("get_info")["height"]

def tip():
    return height() - 1

def classify_block(h):
    try:
        b = seed("get_block", {"height": h})
        bl = json.loads(b["json"])
        sigs = bl.get("signatures", [])
        gov = [s for s in sigs if s["voter_index"] == 65535]
        qrm = [s for s in sigs if s["voter_index"] != 65535]
        ts  = bl.get("timestamp", 0)
        if qrm: return "PULSE", len(qrm), ts
        if gov: return "GOV_SIGNED", 0, ts
        return "MINER", 0, ts
    except Exception as e:
        return "ERR", 0, 0

def sn_list():
    resp = seed("get_service_nodes", {"include_json": False})
    nodes = resp.get("service_node_states", resp.get("service_nodes_infos", []))
    return nodes

def unique_ops_count():
    nodes = sn_list()
    ops = set(n["operator_address"] for n in nodes)
    return len(nodes), len(ops)

def wait_for_height(target, label=""):
    while height() <= target:
        time.sleep(2)
    if label:
        log(f"Reached h={target}: {label}")

# ── Wallet helpers ────────────────────────────────────────────────────────────
GOV_WALLET_PASS = "xeqm-testnet"
OP_WALLET_PASS  = ""

def open_wallet(name):
    try: wallet("close_wallet")
    except: pass
    pw = GOV_WALLET_PASS if name == "testnet-gov" else OP_WALLET_PASS
    wallet("open_wallet", {"filename": name, "password": pw})
    try: wallet("refresh")
    except: pass

def wallet_address(name=None):
    if name:
        open_wallet(name)
    return wallet("get_address", {"account_index": 0})["address"]

def unlocked_balance():
    try: wallet("refresh")
    except: pass
    return wallet("get_balance", {"account_index": 0})["unlocked_balance"]

def wait_wallet_synced(label=""):
    """Poll refresh until blocks_fetched == 0 (fully synced)."""
    for _ in range(120):
        try:
            r = wallet("refresh")
            if r.get("blocks_fetched", 1) == 0:
                return
        except Exception:
            pass
        time.sleep(3)
    log(f"WARNING: wallet sync wait timed out ({label})", level="WARN")

def transfer_to(addr, amount_atomic, priority=1):
    # priority=1 = normal (non-Blink). Required during bootstrap when 0 SNs exist.
    # Retry on ring DB errors — these happen if wallet isn't fully synced yet.
    for attempt in range(5):
        try:
            return wallet("transfer", {
                "destinations": [{"amount": amount_atomic, "address": addr}],
                "priority": priority, "ring_size": 10, "get_tx_key": True,
            })
        except RuntimeError as e:
            if "ring" in str(e).lower() and attempt < 4:
                log(f"Ring DB error (attempt {attempt+1}), resyncing and retrying...")
                wallet("rescan_blockchain")
                wait_wallet_synced("transfer retry")
                time.sleep(5)
                continue
            raise

def ensure_wallet_exists(name):
    # Wallet cache file has no extension in this wallet-rpc version
    cachefile = os.path.join(WALLET_DIR, name)
    if not os.path.exists(cachefile):
        wallet("create_wallet", {"filename": name, "password": "", "language": "English"})
    open_wallet(name)
    return wallet_address()

def start_wallet_rpc():
    # Always kill existing wallet-rpc to avoid stale ring DB across testnet resets.
    subprocess.run(["pkill", "-f", "xeqm-rpc"], capture_output=True)
    time.sleep(2)
    log("Starting wallet-rpc (fresh)...")
    subprocess.Popen([
        XEQM_RPC, "--testnet",
        "--wallet-dir", WALLET_DIR,
        "--rpc-bind-port", "18183",
        "--daemon-address", "127.0.0.1:49001",
        "--disable-rpc-login",
        "--log-level", "0",
    ], stdout=open(f"{LOG_DIR}/wallet-rpc.log","w"), stderr=subprocess.STDOUT)
    for _ in range(40):
        time.sleep(2)
        s = socket.socket()
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", 18183))
            s.close()
            log("wallet-rpc ready")
            return
        except: s.close()
    raise RuntimeError("wallet-rpc did not start in 80s")

# ── SN process management ─────────────────────────────────────────────────────
def is_snode_up(idx):
    port = 49000 + idx * 100 + 1
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except:
        s.close()
        return False

def start_snode(idx):
    p2p  = 49000 + idx * 100
    rpc_p = p2p + 1
    qnet = p2p + 2
    data = os.path.join(DATA_DIR, f"snode{idx}")
    os.makedirs(data, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"snode{idx}.log")
    cmd = [
        XEQMD, "--testnet", "--non-interactive",
        f"--data-dir={data}", "--service-node", "--dev-allow-local-ips",
        f"--p2p-bind-ip=0.0.0.0", f"--p2p-bind-port={p2p}",
        f"--rpc-admin=127.0.0.1:{rpc_p}",
        f"--quorumnet-port={qnet}",
        "--service-node-public-ip=127.0.0.1",
        f"--seed-node=127.0.0.1:{SEED_P2P}",
        f"--add-priority-node=127.0.0.1:{SEED_P2P}",
        "--log-level=pulse:info",
    ]
    with open(log_path, "a") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)
    for _ in range(60):
        time.sleep(2)
        if is_snode_up(idx):
            return proc.pid
    raise RuntimeError(f"snode{idx} RPC didn't come up in 120s")

# ── Registration / deregistration ─────────────────────────────────────────────
def wait_snode_synced(idx, timeout_secs=300):
    """Wait for snode to be at HF22 and within 5 blocks of chain tip before registration."""
    port = 49000 + idx * 100 + 1
    url = f"http://127.0.0.1:{port}/json_rpc"
    for _ in range(timeout_secs // 3):
        try:
            chain_h = tip()
            r = rpc(url, "get_info")
            snode_h = r.get("height", 0) - 1
            if r.get("hard_fork", 0) >= 22 and snode_h >= chain_h - 5:
                return True
        except Exception:
            pass
        time.sleep(3)
    log(f"WARNING: snode{idx} did not reach HF22 near chain tip in {timeout_secs}s", level="WARN")
    return False

def get_snode_pubkey(idx):
    try:
        r = snode_rpc(idx, "get_service_node_status")
        state = r.get("service_node_state", {})
        return state.get("service_node_pubkey", "") or state.get("pubkey", "")
    except:
        return ""

def register_snode(snode_idx, op_wallet_name, op_addr):
    if not wait_snode_synced(snode_idx):
        raise RuntimeError(f"snode{snode_idx} failed to sync before registration")
    snode_url = f"http://127.0.0.1:{49000 + snode_idx*100 + 1}/json_rpc"
    for attempt in range(5):
        try:
            resp = rpc(snode_url, "get_service_node_registration_cmd", {
                "operator_cut": "0",
                "contributor_addresses": [op_addr],
                "contributor_amounts": [STAKING_AMT],
                "staking_requirement": STAKING_AMT,
            })
            reg_cmd = resp.get("registration_cmd", "")
            if not reg_cmd:
                raise RuntimeError("empty registration_cmd")
            break
        except Exception as e:
            log(f"  snode{snode_idx} reg_cmd attempt {attempt+1}: {e}")
            time.sleep(5)
    else:
        raise RuntimeError(f"Could not get registration_cmd from snode{snode_idx}")
    open_wallet(op_wallet_name)
    # priority=1 = normal non-Blink — required during bootstrap (0 SNs = no Blink quorum)
    result = wallet("register_service_node", {
        "register_service_node_str": reg_cmd,
        "priority": 1,
    })
    return result.get("tx_hash", "")

def request_unlock(snode_idx, op_wallet_name):
    """Request stake unlock for a registered snode."""
    pubkey = get_snode_pubkey(snode_idx)
    if not pubkey:
        raise RuntimeError(f"Could not get pubkey for snode{snode_idx}")
    open_wallet(op_wallet_name)
    # priority=1 = non-Blink, safe even during stall phases when SN count is low
    result = wallet("request_stake_unlock", {"service_node_key": pubkey, "priority": 1})
    return result.get("tx_hash", "")

# ── Block monitoring ──────────────────────────────────────────────────────────
_last_logged_h = 0

def poll_blocks(since_h, duration_secs=None, until_pred=None, label=""):
    """
    Yields (h, btype, nsigs, ts) for each new block after since_h.
    Stops after duration_secs wall time OR when until_pred(h, btype) returns True.
    """
    global _last_logged_h
    checked = since_h
    deadline = time.time() + duration_secs if duration_secs else None
    while True:
        if deadline and time.time() > deadline:
            return
        try:
            current = height() - 1
            while checked < current:
                checked += 1
                btype, nsigs, bts = classify_block(checked)
                sn_cnt, op_cnt = unique_ops_count()
                rec = {
                    "h": checked, "type": btype, "sigs": nsigs,
                    "sn_count": sn_cnt, "op_count": op_cnt,
                    "wall_time": now_str(), "elapsed_s": int(time.time()-RUN_START)
                }
                BLOCK_LOG.append(rec)
                if btype == "PULSE":
                    log(f"h={checked}: PULSE[{nsigs}] SNs={sn_cnt} ops={op_cnt}")
                elif checked % 5 == 0 or btype != "GOV_SIGNED":
                    log(f"h={checked}: {btype} SNs={sn_cnt} ops={op_cnt}")
                yield checked, btype, nsigs, bts
                if until_pred and until_pred(checked, btype):
                    return
        except Exception as e:
            log(f"poll error: {e}", level="WARN")
        time.sleep(2)

# ── Phase: setup ─────────────────────────────────────────────────────────────
def phase_setup():
    """Fund 20 operator wallets, register 40 SNs. Returns when all SNs active."""
    log("=" * 70)
    log("PHASE SETUP: Fund operators + register 40 SNs")
    log("=" * 70)

    start_wallet_rpc()
    time.sleep(2)

    # Restore gov wallet (use generate_from_keys — more reliable than restore_deterministic)
    # Wallet cache file has no extension in this wallet-rpc version
    gov_keyfile = os.path.join(WALLET_DIR, "testnet-gov")
    if not os.path.exists(gov_keyfile):
        log("Restoring gov wallet from keys...")
        wallet("generate_from_keys", {
            "filename": "testnet-gov", "password": "xeqm-testnet",
            "address": GOV_ADDRESS, "viewkey": GOV_VIEW_KEY,
            "spendkey": GOV_SPEND_KEY, "restore_height": 0,
        })
    try:
        wallet("close_wallet")
    except: pass
    wallet("open_wallet", {"filename": "testnet-gov", "password": "xeqm-testnet"})
    log("Syncing gov wallet to chain tip...")
    wait_wallet_synced("gov-wallet-open")
    log(f"Gov wallet ready: {wallet_address()[:30]}...")

    # Wait until we have enough XEQM to fund all ops + buffer
    needed = TOTAL_SNS * STAKING_AMT + 500 * COIN
    log(f"Waiting for {needed // COIN} XEQM in gov wallet...")
    while True:
        bal = unlocked_balance()
        log(f"  Gov unlocked: {bal // COIN} XEQM (need {needed // COIN})")
        if bal >= needed:
            break
        time.sleep(20)

    # Create op wallets and fund them
    op_addrs = {}  # op_idx → address
    log("Creating and funding op1-op20 wallets...")
    for op in range(1, NUM_OPS + 1):
        name = f"op{op}"
        addr = ensure_wallet_exists(name)
        op_addrs[op] = addr
        # Check if already funded
        bal = unlocked_balance()
        if bal >= STAKING_AMT * SNS_PER_OP:
            log(f"  {name} already has {bal // COIN} XEQM ✓")
            continue
        # Fund from gov — wait 2 blocks between transfers to avoid mempool-decoy conflicts
        open_wallet("testnet-gov")
        wait_wallet_synced("pre-fund")
        need = STAKING_AMT * SNS_PER_OP - bal
        tx = transfer_to(addr, need + 5 * COIN)  # +5 for tx fees
        log(f"  Funded {name}: tx={tx['tx_hash'][:16]}...")
        fund_h = height()
        for _ in poll_blocks(fund_h, until_pred=lambda h, _: h >= fund_h + 2):
            pass  # wait 2 blocks for TX to mine before next transfer

    # Wait for funding TXs to unlock (10 blocks)
    fund_height = tip()
    target = fund_height + 12
    log(f"Waiting for funding TXs to unlock at h≥{target}...")
    for _ in poll_blocks(fund_height, until_pred=lambda h, _: h >= target):
        pass

    # Start snode processes if not already running
    for idx in range(1, TOTAL_SNS + 1):
        if not is_snode_up(idx):
            log(f"  Starting snode{idx}...")
            start_snode(idx)

    # Refresh op wallets and verify balances
    for op in range(1, NUM_OPS + 1):
        open_wallet(f"op{op}")
        bal = unlocked_balance()
        if bal < STAKING_AMT * SNS_PER_OP:
            log(f"  WARNING op{op} has only {bal // COIN} XEQM, need {STAKING_AMT * SNS_PER_OP // COIN}", level="WARN")

    # Register all SNs in two waves to avoid per-op balance race conditions.
    # Wave 1 registers the first SN per op. After 15 blocks the wave-1 change
    # matures and wave 2 can spend it for the second SN per op.
    # Layout: op1→snode1,snode2; op2→snode3,snode4; ... op20→snode39,snode40
    registered = {}  # snode_idx → tx_hash

    log("Registering SNs — wave 1 (first SN per operator)...")
    for op in range(1, NUM_OPS + 1):
        snode_idx = (op - 1) * SNS_PER_OP + 1  # slot 0
        log(f"  Registering snode{snode_idx} with op{op}...")
        try:
            tx = register_snode(snode_idx, f"op{op}", op_addrs[op])
            registered[snode_idx] = tx
            log(f"    TX: {tx[:16]}...")
        except Exception as e:
            log(f"    ERROR snode{snode_idx}: {e}", level="ERROR")
        time.sleep(0.5)

    # Wait 15 blocks for wave-1 TXs to confirm and change to mature
    wave1_target = tip() + 15
    log(f"Wave 1 sent. Waiting for h={wave1_target} (15 blocks for change maturity)...")
    for _ in poll_blocks(tip(), until_pred=lambda h, _: h >= wave1_target):
        pass

    log("Registering SNs — wave 2 (second SN per operator)...")
    for op in range(1, NUM_OPS + 1):
        snode_idx = (op - 1) * SNS_PER_OP + 2  # slot 1
        log(f"  Registering snode{snode_idx} with op{op}...")
        try:
            tx = register_snode(snode_idx, f"op{op}", op_addrs[op])
            registered[snode_idx] = tx
            log(f"    TX: {tx[:16]}...")
        except Exception as e:
            log(f"    ERROR snode{snode_idx}: {e}", level="ERROR")
        time.sleep(0.5)

    event("setup_registrations_sent", count=len(registered))

    # Wait for all SNs to appear in active list
    log("Waiting for all 40 SNs to become active...")
    reg_height = tip()
    for _ in range(600):
        time.sleep(5)
        sn_cnt, op_cnt = unique_ops_count()
        log(f"  h={tip()}: SNs={sn_cnt}/40, ops={op_cnt}/20")
        if sn_cnt >= TOTAL_SNS and op_cnt >= NUM_OPS:
            break
    else:
        log("WARNING: not all SNs active after timeout", level="WARN")

    # Wait for uptime proofs to propagate (30s window for 120s validity)
    log("Waiting 15 blocks for uptime proof propagation...")
    target = tip() + 15
    for _ in poll_blocks(tip(), until_pred=lambda h, _: h >= target):
        pass

    sn_cnt, op_cnt = unique_ops_count()
    event("setup_complete", sn_count=sn_cnt, op_count=op_cnt)
    log(f"Setup complete: h={tip()}, SNs={sn_cnt}, ops={op_cnt}")
    return op_addrs

# ── Phase: wait for HF22 + pre-HF22 Pulse baseline ──────────────────────────
def phase_pre_hf22():
    log("=" * 70)
    log("PHASE PRE-HF22: Watching for Pulse baseline before block 250")
    log("=" * 70)

    pulse_count = 0
    start_h = tip()

    for h, btype, nsigs, _ in poll_blocks(start_h):
        if btype == "PULSE":
            pulse_count += 1

        # Once HF22 fires (block 250), check if Pulse still runs (it should with 20 ops)
        if h >= 250:
            log(f"HF22 fired at h=250. Pulse count so far: {pulse_count}")
            event("hf22_fired", height=250, pulse_pre_hf22=pulse_count)
            break

    # Let Pulse run post-HF22 for 30 blocks to confirm dedup works at 20 ops
    log("Post-HF22: confirming Pulse continues with 20 unique ops (>> 12 threshold)...")
    post_pulse = 0
    for h, btype, nsigs, _ in poll_blocks(tip(), until_pred=lambda h, _: h >= 280):
        if btype == "PULSE":
            post_pulse += 1

    event("post_hf22_baseline", pulse_blocks=post_pulse, height=tip())
    log(f"Post-HF22 baseline: {post_pulse} Pulse blocks in 30 blocks. Proceeding to stall cycles.")

# ── Phase: stall cycle ────────────────────────────────────────────────────────
def run_stall_recovery_cycle(cycle_num, op_addrs):
    log("=" * 70)
    log(f"STALL CYCLE {cycle_num}")
    log("=" * 70)

    # -- Step 1: Random Pulse observation before stall -----------------------
    pulse_run_secs = random.uniform(STALL_INTERVAL_MIN_SECS, STALL_INTERVAL_MAX_SECS)
    log(f"Running Pulse for {pulse_run_secs/60:.1f} min before stall...")
    pulse_before = 0
    run_start_h = tip()
    deadline = time.time() + pulse_run_secs
    for h, btype, nsigs, _ in poll_blocks(run_start_h, duration_secs=pulse_run_secs):
        if btype == "PULSE":
            pulse_before += 1
        elif btype == "GOV_SIGNED" and h > run_start_h + 5:
            log(f"WARNING: unexpected GOV_SIGNED at h={h} during Pulse run", level="WARN")
            event("unexpected_stall", height=h, cycle=cycle_num)

    event("stall_cycle_start", cycle=cycle_num, pulse_run_secs=pulse_run_secs,
          pulse_blocks_before=pulse_before, height=tip())

    # -- Step 2: Deregister op11-op20 (10 operators) -------------------------
    transient_count = TRANSIENT_OPS_END - TRANSIENT_OPS_START + 1
    log(f"Deregistering op{TRANSIENT_OPS_START}-op{TRANSIENT_OPS_END} ({transient_count} operators, {transient_count * SNS_PER_OP} SNs)...")
    dereg_txs = {}
    for op in range(TRANSIENT_OPS_START, TRANSIENT_OPS_END + 1):
        for slot in range(SNS_PER_OP):
            snode_idx = (op - 1) * SNS_PER_OP + slot + 1
            try:
                tx = request_unlock(snode_idx, f"op{op}")
                dereg_txs[snode_idx] = tx
                log(f"  snode{snode_idx} unlock TX: {tx[:16]}...")
            except Exception as e:
                log(f"  ERROR unlocking snode{snode_idx}: {e}", level="ERROR")
        time.sleep(0.3)

    dereg_height = tip()
    unlock_height = dereg_height + UNLOCK_BLOCKS
    event("stall_deregister", cycle=cycle_num, ops_deregistered=list(range(TRANSIENT_OPS_START, TRANSIENT_OPS_END+1)),
          dereg_height=dereg_height, unlock_height=unlock_height, tx_count=len(dereg_txs))

    # -- Step 3: Confirm stall (watch for all GOV_SIGNED) -------------------
    log(f"Watching for stall confirmation (expect ≤12 unique ops)...")
    stall_confirmed_h = None
    gov_count = 0
    for h, btype, nsigs, _ in poll_blocks(dereg_height, until_pred=lambda h, _: h >= dereg_height + 20):
        sn_cnt, op_cnt = unique_ops_count()
        if btype == "GOV_SIGNED" and op_cnt <= STALL_THRESHOLD and stall_confirmed_h is None:
            stall_confirmed_h = h
            event("stall_confirmed", cycle=cycle_num, height=h, unique_ops=op_cnt)
            log(f"STALL CONFIRMED at h={h}: {op_cnt} unique ops (≤{STALL_THRESHOLD})")
        if btype == "GOV_SIGNED":
            gov_count += 1

    if stall_confirmed_h is None:
        log("WARNING: stall not confirmed after 20 blocks", level="WARN")

    # -- Step 4: Wait for unlock (UNLOCK_BLOCKS GOV blocks after dereg) ------
    log(f"Waiting for unlock at h={unlock_height} (~{UNLOCK_BLOCKS} blocks)...")
    for _ in poll_blocks(tip(), until_pred=lambda h, _: h >= unlock_height + 2):
        pass
    log(f"Unlock window passed (h={tip()})")

    # -- Step 5: Recovery phase 1 - re-register first transient op (minimum threshold) ---
    op_start = TRANSIENT_OPS_START
    op_start_addr = op_addrs[op_start]
    log(f"RECOVERY PHASE 1: Re-registering op{op_start} only (→ {CORE_OPS + 1} unique ops, tests minimum threshold)...")
    recovery1_txs = []
    for slot in range(SNS_PER_OP):
        snode_idx = (op_start - 1) * SNS_PER_OP + slot + 1
        try:
            tx = register_snode(snode_idx, f"op{op_start}", op_start_addr)
            recovery1_txs.append(tx)
            log(f"  Registered snode{snode_idx} with op{op_start}: {tx[:16]}...")
        except Exception as e:
            log(f"  ERROR re-registering snode{snode_idx}: {e}", level="ERROR")

    recovery1_height = tip()
    event("recovery1_start", cycle=cycle_num, height=recovery1_height, ops_added=[op_start])

    # -- Step 6: Confirm Pulse resumes with CORE_OPS+1 unique ops --------------------
    log(f"Waiting for Pulse resumption (op{op_start} back → {CORE_OPS + 1} unique ops)...")
    pulse_resume_h = None
    for h, btype, nsigs, _ in poll_blocks(recovery1_height, until_pred=lambda h, _: h >= recovery1_height + 60):
        if btype == "PULSE" and pulse_resume_h is None:
            pulse_resume_h = h
            sn_cnt, op_cnt = unique_ops_count()
            recovery_blocks = h - (stall_confirmed_h or dereg_height)
            event("recovery1_confirmed", cycle=cycle_num, height=h, unique_ops=op_cnt,
                  pulse_sigs=nsigs, stall_duration_blocks=recovery_blocks)
            log(f"RECOVERY 1 CONFIRMED at h={h}: PULSE[{nsigs}], {op_cnt} unique ops")
            log(f"  Stall duration: {recovery_blocks} blocks")
            break

    if pulse_resume_h is None:
        log("WARNING: Pulse did not resume after 60 blocks", level="WARN")
        event("recovery1_failed", cycle=cycle_num, height=tip())
        return False

    # -- Step 7: Recovery phase 2 - re-register remaining transient ops -------------------
    log(f"RECOVERY PHASE 2: Re-registering op{TRANSIENT_OPS_START + 1}-op{TRANSIENT_OPS_END} (→ {NUM_OPS} unique ops, full fleet)...")
    for op in range(TRANSIENT_OPS_START + 1, TRANSIENT_OPS_END + 1):
        addr = op_addrs[op]
        for slot in range(SNS_PER_OP):
            snode_idx = (op - 1) * SNS_PER_OP + slot + 1
            try:
                tx = register_snode(snode_idx, f"op{op}", addr)
                log(f"  Re-registered snode{snode_idx} with op{op}: {tx[:16]}...")
            except Exception as e:
                log(f"  ERROR re-registering snode{snode_idx}: {e}", level="ERROR")
        time.sleep(0.3)

    # Wait for full fleet to come back
    target = tip() + 20
    for _ in poll_blocks(tip(), until_pred=lambda h, _: h >= target):
        pass

    sn_cnt, op_cnt = unique_ops_count()
    event("recovery2_complete", cycle=cycle_num, height=tip(), sn_count=sn_cnt, op_count=op_cnt)
    log(f"CYCLE {cycle_num} COMPLETE: h={tip()}, SNs={sn_cnt}, ops={op_cnt}")
    return True

# ── Post-run report ───────────────────────────────────────────────────────────
def write_report(report_path):
    total_blocks = len(BLOCK_LOG)
    pulse_blocks = [b for b in BLOCK_LOG if b["type"] == "PULSE"]
    gov_blocks   = [b for b in BLOCK_LOG if b["type"] == "GOV_SIGNED"]

    stall_events     = [e for e in EVENT_LOG if e["kind"] == "stall_confirmed"]
    recovery1_events = [e for e in EVENT_LOG if e["kind"] == "recovery1_confirmed"]
    recovery1_failed = [e for e in EVENT_LOG if e["kind"] == "recovery1_failed"]

    lines = []
    lines.append("HF22 PULSE STALL/RECOVERY 12-HOUR TEST REPORT")
    lines.append("=" * 60)
    lines.append(f"Run start:    {datetime.fromtimestamp(RUN_START).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Run end:      {now_str()}")
    lines.append(f"Duration:     {elapsed()}")
    lines.append(f"Blocks logged: {total_blocks}")
    lines.append(f"PULSE blocks: {len(pulse_blocks)} ({100*len(pulse_blocks)/max(total_blocks,1):.1f}%)")
    lines.append(f"GOV_SIGNED:   {len(gov_blocks)} ({100*len(gov_blocks)/max(total_blocks,1):.1f}%)")
    lines.append("")
    lines.append("STALL/RECOVERY CYCLES")
    lines.append("-" * 60)
    lines.append(f"{'Cycle':>5} {'Stall h':>8} {'Ops@stall':>9} {'Resume h':>8} {'Stall dur':>9} {'Result':>8}")
    lines.append("-" * 60)
    for i, se in enumerate(stall_events):
        cycle = se.get("cycle", i+1)
        re_list = [r for r in recovery1_events if r.get("cycle") == cycle]
        rf_list = [r for r in recovery1_failed if r.get("cycle") == cycle]
        if re_list:
            re = re_list[0]
            dur = re.get("stall_duration_blocks", "?")
            lines.append(f"{cycle:>5} {se['height']:>8} {se['unique_ops']:>9} {re['height']:>8} {str(dur)+' blk':>9} {'PASS':>8}")
        elif rf_list:
            lines.append(f"{cycle:>5} {se['height']:>8} {se['unique_ops']:>9} {'—':>8} {'—':>9} {'FAIL':>8}")
        else:
            lines.append(f"{cycle:>5} {se['height']:>8} {se['unique_ops']:>9} {'pending':>8} {'—':>9} {'—':>8}")

    lines.append("")
    lines.append(f"Cycles completed: {len(stall_events)}")
    lines.append(f"Recoveries confirmed: {len(recovery1_events)}")
    lines.append(f"Recovery failures: {len(recovery1_failed)}")

    report_text = "\n".join(lines)
    report_json = {"events": EVENT_LOG, "blocks": BLOCK_LOG,
                   "summary": {
                       "total_blocks": total_blocks,
                       "pulse_blocks": len(pulse_blocks),
                       "gov_blocks": len(gov_blocks),
                       "cycles": len(stall_events),
                       "recoveries": len(recovery1_events),
                   }}

    Path(report_path + ".txt").write_text(report_text)
    Path(report_path + ".json").write_text(json.dumps(report_json, indent=2))
    log(f"Report written to {report_path}.txt and .json")
    print(report_text)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-hours", type=float, default=12.0)
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--skip-setup", action="store_true",
                        help="Skip setup phase; assume SNs already registered")
    parser.add_argument("--start-cycle", type=int, default=1,
                        help="Start from this cycle number (for resume)")
    args = parser.parse_args()

    deadline = time.time() + args.duration_hours * 3600
    report_path = f"/home/svshearer/xeqm-testnet/report-{datetime.now().strftime('%Y%m%d-%H%M')}"

    log(f"HF22 12-hour stall/recovery test starting")
    log(f"Duration: {args.duration_hours}h, deadline: {datetime.fromtimestamp(deadline).strftime('%H:%M:%S')}")
    log(f"Config: {NUM_OPS} ops, {TOTAL_SNS} SNs, UNLOCK_BLOCKS={UNLOCK_BLOCKS}, HF22=250")

    try:
        if not args.skip_setup:
            op_addrs = phase_setup()
        else:
            # Rebuild op_addrs from existing wallets
            start_wallet_rpc()
            op_addrs = {}
            for op in range(1, NUM_OPS + 1):
                op_addrs[op] = wallet_address(f"op{op}")
            log("Skipped setup, loaded existing op addresses")

        if args.setup_only:
            log("--setup-only: stopping after setup")
            write_report(report_path)
            return

        phase_pre_hf22()

        cycle = args.start_cycle
        while time.time() < deadline:
            remaining = (deadline - time.time()) / 3600
            log(f"--- Cycle {cycle} start (remaining: {remaining:.1f}h) ---")
            ok = run_stall_recovery_cycle(cycle, op_addrs)
            if not ok:
                log(f"Cycle {cycle} recovery FAILED — stopping", level="ERROR")
                event("test_aborted", cycle=cycle, reason="recovery_failed")
                break
            cycle += 1
            if time.time() >= deadline:
                break

        event("test_complete", cycles=cycle-1, elapsed_s=int(time.time()-RUN_START))
        log(f"Test complete. Completed {cycle-1} stall/recovery cycles.")

    except KeyboardInterrupt:
        log("Interrupted by user")
        event("test_interrupted", elapsed_s=int(time.time()-RUN_START))

    finally:
        write_report(report_path)

if __name__ == "__main__":
    main()
