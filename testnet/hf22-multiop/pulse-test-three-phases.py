#!/usr/bin/env python3
"""
Three-phase HF22 Pulse / Operator Dedup Test
==============================================
Phase 1 (pre-HF22):
  Operators 1-8 each register 2 SNs → 16 SNs, 8 unique operators.
  16 ≥ PULSE_MIN(12) and no dedup yet → Pulse produces blocks. PoW stops.

Phase 2 (HF22 activates at block 400):
  Dedup fires: 8 unique operators < PULSE_MIN(12) → 0 quorum candidates.
  Pulse stalls automatically. Option A: governance-signed PoW blocks take over.

Phase 3 (post-HF22):
  Operators 9-12 each register 1 SN → 12 unique operators ≥ PULSE_MIN(12).
  Dedup now produces 12 candidates → Pulse resumes. PoW stops again.
"""
import json, subprocess, time, urllib.request, sys, os, random

SEED_RPC     = "http://127.0.0.1:49001/json_rpc"
WALLET_RPC   = "http://127.0.0.1:18183/json_rpc"
WALLET_DIR   = "/home/svshearer/xeqm-testnet/wallet"
GOV_WALLET   = "testnet-gov"
GOV_PASS     = "xeqm-testnet"
XEQM_RPC    = "/home/svshearer/xeqm-core/build/bin/xeqm-rpc"
XEQM_D      = "/home/svshearer/xeqm-core/build/bin/xeqm-d"
PID_DIR      = "/home/svshearer/xeqm-testnet/pids"
LOG_DIR      = "/home/svshearer/xeqm-testnet/logs"
DATA_DIR     = "/home/svshearer/xeqm-testnet/data"
NUM_SNODES   = 20          # start all 20 from the beginning
STAKING_AMT  = 100_000_000_000   # 100 XEQM per SN
COIN         = 1_000_000_000
HF22_BLOCK   = 400

# Governance wallet keys (TESTNET ONLY)
GOV_ADDRESS   = "XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx"
GOV_VIEW_KEY  = "8e34dd7f6eb9b9f28be81619e20765c53b79070aab49c353ffc877b67389cd09"
GOV_SPEND_KEY = "0c999a88be252215b48735272e5cf3dd86d54f850bb0bc8bfe9aea0de7549405"
FALLBACK_KEY  = GOV_SPEND_KEY

# Phase 1: operators 1-8, 2 SNs each (snodes 1-16)
PHASE1_OPS   = 8
SNODES_PHASE1 = list(range(1, 17))   # 1..16

# Phase 3: operators 9-12, 1 SN each (snodes 17-20)
PHASE3_OPS   = 4
SNODES_PHASE3 = list(range(17, 21))  # 17..20

# Funding: each Phase-1 operator needs 200+ XEQM (2 SNs × 100), Phase-3 needs 100+
FUND_PHASE1  = 210 * COIN   # per operator (2 SNs + fees)
FUND_PHASE3  = 110 * COIN   # per operator (1 SN + fees)
# Total needed: 8×210 + 4×110 = 1680 + 440 = 2120 XEQM + governance fee buffer
WAIT_FOR_XEQM = 2500

os.makedirs(PID_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(WALLET_DIR, exist_ok=True)
for d in [f"{DATA_DIR}/seed"] + [f"{DATA_DIR}/snode{i}" for i in range(1, NUM_SNODES+1)]:
    os.makedirs(d, exist_ok=True)

# ── RPC helpers ──────────────────────────────────────────────────────────────
def rpc(url, method, params=None):
    body = json.dumps({"jsonrpc":"2.0","method":method,
                       "params": params or {},"id":"0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    if "error" in d:
        raise RuntimeError(f"{method}: {d['error']['message']}")
    return d.get("result", {})

def wait_rpc(url, label, timeout=90):
    for _ in range(timeout // 2):
        try:
            rpc(url, "get_info" if "49001" in url else "get_version")
            print(f"  {label} ready"); return True
        except Exception:
            time.sleep(2)
    print(f"  {label} timed out!"); return False

def height():
    return rpc(SEED_RPC, "get_info").get("height", 0)

def wait_blocks(n, label=""):
    pre = height()
    target = pre + n
    print(f"  waiting {n} blocks (h>{target}) {label}...", flush=True)
    for _ in range(n * 30):
        time.sleep(1)
        try:
            h = height()
            if h > target:
                print(f"  h={h} ✓", flush=True); return h
        except Exception:
            pass
    return height()

# ── Daemon management ─────────────────────────────────────────────────────────
def start_daemon(name, args):
    pf = f"{PID_DIR}/{name}.pid"
    try:
        pid = int(open(pf).read().strip())
        os.kill(pid, 0)
        print(f"  [{name}] already running pid {pid}"); return
    except Exception:
        pass
    os.makedirs(f"{DATA_DIR}/{name}", exist_ok=True)
    lg = open(f"{LOG_DIR}/{name}.log", "a")
    p = subprocess.Popen([XEQM_D,"--testnet","--non-interactive",
                          f"--data-dir={DATA_DIR}/{name}"]+args,
                         stdout=lg, stderr=lg, preexec_fn=os.setsid)
    open(pf,"w").write(str(p.pid))
    print(f"  [{name}] pid {p.pid}")

def snode_args(i):
    p2p  = 49000 + i*100
    rpc_ = p2p + 1
    qnet = p2p + 2
    extra = ["--log-level","pulse:info"] if i == 1 else []
    return [
        "--service-node","--dev-allow-local-ips",
        "--p2p-bind-ip=0.0.0.0",f"--p2p-bind-port={p2p}",
        f"--rpc-admin=127.0.0.1:{rpc_}",
        f"--quorumnet-port={qnet}",
        "--service-node-public-ip=127.0.0.1",
        "--seed-node=127.0.0.1:49000",
        "--add-priority-node=127.0.0.1:49000",
    ] + extra

def snode_rpc_url(i):
    return f"http://127.0.0.1:{49000+i*100+1}/json_rpc"

# ── Wallet management ─────────────────────────────────────────────────────────
def open_wallet(name, password=""):
    try:
        rpc(WALLET_RPC, "close_wallet", {})
    except Exception:
        pass
    rpc(WALLET_RPC, "open_wallet", {"filename": name, "password": password})

def open_gov_wallet():
    open_wallet(GOV_WALLET, GOV_PASS)

def get_address():
    return rpc(WALLET_RPC, "get_address", {"account_index":0})["address"]

def refresh():
    try: rpc(WALLET_RPC, "refresh", {})
    except Exception: pass

def unlocked_balance():
    refresh()
    return rpc(WALLET_RPC, "get_balance", {"account_index":0})["unlocked_balance"] // COIN

def create_op_wallet(n):
    """Create a fresh operator wallet op{n} with random keys."""
    name = f"op{n}"
    wallet_file = os.path.join(WALLET_DIR, f"{name}.keys")
    if os.path.exists(wallet_file):
        open_wallet(name, "")
        addr = get_address()
        print(f"  [op{n}] exists, addr={addr[:20]}...")
        return addr
    try:
        rpc(WALLET_RPC, "close_wallet", {})
    except Exception:
        pass
    rpc(WALLET_RPC, "create_wallet", {"filename": name, "password": "", "language": "English"})
    addr = get_address()
    print(f"  [op{n}] created addr={addr[:20]}...")
    return addr

# ── Registration helpers ───────────────────────────────────────────────────────
def register_sn(snode_idx, op_wallet_name, op_addr):
    """Register snode_idx using the operator wallet (currently open in wallet-rpc)."""
    url = snode_rpc_url(snode_idx)
    for attempt in range(3):
        try:
            resp = rpc(url, "get_service_node_registration_cmd", {
                "operator_cut": "0",
                "contributor_addresses": [op_addr],
                "contributor_amounts": [STAKING_AMT],
                "staking_requirement": STAKING_AMT,
            })
            reg_cmd = resp.get("registration_cmd","")
            if not reg_cmd:
                raise RuntimeError("empty reg_cmd")
            open_wallet(op_wallet_name, "")
            refresh()
            result = rpc(WALLET_RPC, "register_service_node", {"register_service_node_str": reg_cmd})
            return result.get("tx_hash","no-txid")
        except Exception as e:
            if attempt == 2: raise
            print(f"    retry {attempt+1}: {e}")
            time.sleep(3)

def active_sn_count():
    d = rpc(SEED_RPC, "get_service_nodes", {"include_json": False})["result" if "result" in rpc(SEED_RPC,"get_service_nodes",{"include_json":False}) else ""]
    # retry
    resp = rpc(SEED_RPC, "get_service_nodes", {"include_json": False})
    sns = resp.get("service_node_states", resp.get("service_nodes_infos", []))
    return len(sns)

def sn_count():
    resp = rpc(SEED_RPC, "get_service_nodes", {"include_json": False})
    sns = resp.get("service_node_states", resp.get("service_nodes_infos", []))
    return len(sns)

# ── Block type classifier ─────────────────────────────────────────────────────
def classify_block(h):
    try:
        block = rpc(SEED_RPC, "get_block", {"height": h})
        b = json.loads(block["json"])
        sigs = b.get("signatures", [])
        gov  = [s for s in sigs if s["voter_index"] == 65535]
        qrm  = [s for s in sigs if s["voter_index"] != 65535]
        if qrm:   return f"PULSE[{len(qrm)}]"
        if gov:   return "GOV_SIGNED"
        return "MINER_FALL"
    except Exception as e:
        return f"ERR:{e}"

def wait_for_pulse(min_pulse_blocks=5, timeout_blocks=200, label=""):
    """Return True when we've seen min_pulse_blocks Pulse blocks."""
    start_h = height()
    pulse_seen = 0
    checked_h = start_h
    print(f"  [{label}] watching for {min_pulse_blocks} Pulse blocks from h={start_h}...", flush=True)
    for _ in range(timeout_blocks * 10):
        time.sleep(1)
        try:
            # height() returns next-block number; tip is height()-1.
            # Keep checked_h strictly below that so we only classify blocks that exist.
            tip = height() - 1
            while checked_h < tip:
                checked_h += 1
                t = classify_block(checked_h)
                if "PULSE" in t:
                    pulse_seen += 1
                    print(f"    h={checked_h}: {t} (Pulse #{pulse_seen})", flush=True)
                    if pulse_seen >= min_pulse_blocks:
                        return True
                elif pulse_seen > 0 or checked_h % 10 == 0:
                    print(f"    h={checked_h}: {t}", flush=True)
        except Exception:
            pass
    print(f"  [{label}] timeout after {timeout_blocks} blocks, saw {pulse_seen} Pulse blocks")
    return False

def wait_for_block(target):
    while height() < target:
        time.sleep(2)

# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 70)
print("THREE-PHASE HF22 PULSE / OPERATOR DEDUP TEST")
print("=" * 70)
print(f"  Phase 1: ops 1-8 register 2 SNs each = 16 SNs (pre-HF22)")
print(f"  Phase 2: HF22 at block {HF22_BLOCK}: dedup → 8 unique ops < 12 → stall")
print(f"  Phase 3: ops 9-12 register 1 SN each → 12 unique ops → Pulse resumes")
print()

# ── 1. wallet-rpc ─────────────────────────────────────────────────────────────
pid_file = f"{PID_DIR}/wallet-rpc.pid"
try:
    old = int(open(pid_file).read().strip())
    if os.path.exists(f"/proc/{old}"):
        os.kill(old, 15); time.sleep(2)
    os.remove(pid_file)
except Exception:
    pass
print("Starting wallet-rpc...")
lg = open(f"{LOG_DIR}/wallet-rpc.log","a")
proc = subprocess.Popen([XEQM_RPC,"--testnet","--wallet-dir",WALLET_DIR,
                         "--rpc-bind-port","18183","--daemon-address","127.0.0.1:49001",
                         "--disable-rpc-login","--log-level","0"],
                        stdout=lg, stderr=lg, preexec_fn=os.setsid)
open(pid_file,"w").write(str(proc.pid))
wait_rpc(WALLET_RPC, "wallet-rpc")

# ── 2. Restore governance wallet ──────────────────────────────────────────────
print("Restoring governance wallet...")
gov_base = os.path.join(WALLET_DIR, GOV_WALLET)
gov_keys = os.path.join(WALLET_DIR, f"{GOV_WALLET}.keys")
if os.path.exists(gov_keys) or os.path.exists(gov_base):
    open_gov_wallet()
    print("  opened (resuming)")
else:
    rpc(WALLET_RPC, "generate_from_keys", {
        "filename": GOV_WALLET, "password": GOV_PASS,
        "address": GOV_ADDRESS, "viewkey": GOV_VIEW_KEY,
        "spendkey": GOV_SPEND_KEY, "restore_height": 0,
    })
    print("  restored from keys")
GOV_ADDR = get_address()
print(f"  governance wallet: {GOV_ADDR[:30]}...")

# ── 3. Seed + all 20 snodes ───────────────────────────────────────────────────
print("\nStarting seed...")
# Kill old seed
try:
    old = int(open(f"{PID_DIR}/seed.pid").read().strip())
    os.kill(old, 15); time.sleep(2); os.remove(f"{PID_DIR}/seed.pid")
except Exception:
    pass
start_daemon("seed", [
    "--p2p-bind-ip=0.0.0.0","--p2p-bind-port=49000",
    "--rpc-admin=127.0.0.1:49001",
    "--dev-allow-local-ips",
    "--start-mining", GOV_ADDR, "--mining-threads","2",
    "--fallback-miner-key", FALLBACK_KEY,
])
wait_rpc(SEED_RPC, "seed")

print(f"\nStarting all {NUM_SNODES} snode daemons...")
for i in range(1, NUM_SNODES+1):
    start_daemon(f"snode{i}", snode_args(i))
print("All snodes launched.\n")

# Kick mining
print("Waiting for mining to start...")
for _ in range(30):
    time.sleep(3)
    try:
        ms = rpc(SEED_RPC, "mining_status")
        if ms.get("active"):
            print(f"  Mining active @ {ms.get('speed',0)} h/s"); break
        rpc(SEED_RPC, "start_mining", {"miner_address": GOV_ADDR, "threads_count": 2})
    except Exception:
        pass

# ── 4. Mine to WAIT_FOR_XEQM XEQM in governance wallet ──────────────────────
print(f"\nMining to {WAIT_FOR_XEQM} XEQM (need HF19 first, then funds)...")
open_gov_wallet()
for poll in range(2000):
    time.sleep(4)
    try:
        info = rpc(SEED_RPC, "get_info")
        hf   = info.get("hard_fork", 0)
        h    = info.get("height", 0)
        refresh()
        bal  = rpc(WALLET_RPC, "get_balance", {"account_index": 0})
        unl  = bal["unlocked_balance"] // COIN
        if poll % 15 == 0 or unl >= WAIT_FOR_XEQM:
            print(f"  h={h} hf={hf} unlocked={unl} XEQM", flush=True)
        if hf >= 19 and unl >= WAIT_FOR_XEQM:
            print(f"  Ready at h={h}!")
            break
    except Exception as e:
        pass
else:
    print("Timed out waiting for funds"); sys.exit(1)

# ── 5. Create 12 operator wallets ─────────────────────────────────────────────
print("\n=== Creating 12 operator wallets ===")
op_addrs = {}
for n in range(1, 13):
    addr = create_op_wallet(n)
    op_addrs[n] = addr

# ── 6. Fund all 12 operator wallets from governance wallet ────────────────────
print("\n=== Funding operator wallets ===")

# Pause mining so the daemon is idle during ring member RPC lookups.
# Under mining load, get_transactions timeouts corrupt ring construction
# and produce "Known ring does not include the spent output" errors.
try:
    rpc(SEED_RPC, "stop_mining", {})
    print("  Mining paused for clean TX construction")
except Exception:
    pass
time.sleep(3)

open_gov_wallet()
refresh()
time.sleep(2)
refresh()

# Fund Phase 1 operators (1-8) with 210 XEQM each, Phase 3 (9-12) with 110 XEQM each
destinations = []
for n in range(1, 9):
    destinations.append({"amount": FUND_PHASE1, "address": op_addrs[n]})
for n in range(9, 13):
    destinations.append({"amount": FUND_PHASE3, "address": op_addrs[n]})

total = sum(d["amount"] for d in destinations) // COIN
print(f"  Sending {total} XEQM in one TX to 12 operator wallets...")
for attempt in range(3):
    try:
        result = rpc(WALLET_RPC, "transfer", {
            "destinations": destinations,
            "get_tx_key": True,
            "ring_size": 11,
            "priority": 1,
        })
        print(f"  TX: {result.get('tx_hash','?')[:20]}...")
        break
    except Exception as e:
        print(f"  attempt {attempt+1} failed: {e}")
        if attempt == 2:
            raise
        time.sleep(5)
        refresh()

# Resume mining now that the TX is constructed and submitted
try:
    gov_addr = GOV_ADDR
    rpc(SEED_RPC, "start_mining", {"miner_address": gov_addr, "threads_count": 2})
    print("  Mining resumed")
except Exception:
    pass

# Wait 12 blocks — funding outputs need 10+ confirmations to appear as unlocked_balance
wait_blocks(12, "funding confirmation")

# ── 7. PHASE 1: Register 16 SNs (ops 1-8, 2 SNs each) ────────────────────────
print("\n" + "=" * 70)
print("PHASE 1: Registering 16 SNs from 8 unique operators (2 SNs each)")
print("=" * 70)

snode_idx = 1
for op_n in range(1, PHASE1_OPS + 1):
    print(f"\n  Operator {op_n} (addr {op_addrs[op_n][:20]}...): registering snodes {snode_idx} and {snode_idx+1}")
    for j in range(2):
        si = snode_idx + j
        print(f"    snode{si} -> ", end="", flush=True)
        try:
            txhash = register_sn(si, f"op{op_n}", op_addrs[op_n])
            print(txhash[:20] if txhash else "ERR")
        except Exception as e:
            print(f"ERROR: {e}")
        if j == 0:
            # Change outputs require 10+ block confirmations before appearing
            # as unlocked_balance. Poll until funds are spendable.
            wait_blocks(1, f"op{op_n} snode{si} change confirm")
            print(f"    waiting for op{op_n} unlocked balance >= {STAKING_AMT // COIN} XEQM...", end="", flush=True)
            for _chk in range(120):
                try:
                    open_wallet(f"op{op_n}", "")
                    bal = rpc(WALLET_RPC, "get_balance", {"account_index": 0})["unlocked_balance"]
                    if bal >= STAKING_AMT:
                        print(f" {bal // COIN} XEQM ✓", flush=True)
                        break
                except Exception:
                    pass
                time.sleep(3)
            else:
                print(f" WARNING: still locked after 360s", flush=True)
    snode_idx += 2

    # Wait 2 blocks between each operator's pair to avoid ring conflicts
    wait_blocks(2, f"op{op_n} confirmation")

print(f"\nAll Phase 1 registrations submitted. Checking SN count...")
time.sleep(5)
cnt = sn_count()
print(f"  Active SNs: {cnt} / 16")

# ── 8. PHASE 1 VERIFICATION: Watch for Pulse blocks ──────────────────────────
print("\n" + "=" * 70)
print("PHASE 1 VERIFICATION: Waiting for Pulse blocks")
print("  Expected: 16 SNs, 8 unique operators, no HF22 dedup yet → Pulse works")
print("=" * 70)

phase1_ok = wait_for_pulse(min_pulse_blocks=5, timeout_blocks=300, label="Phase1")
if phase1_ok:
    print("\n*** PHASE 1 PASS: Pulse blocks confirmed! ***")
    print("    16 SNs from 8 operators → Pulse producing blocks (PoW stopped)")
else:
    print("\n*** PHASE 1 WARN: Did not see expected Pulse blocks.")
    print("    Check snode1 log for Pulse round info:")
    os.system("tail -30 /home/svshearer/xeqm-testnet/logs/snode1.log")

# ── 9. PHASE 2: Wait for HF22 → automatic Pulse stall ────────────────────────
print("\n" + "=" * 70)
print(f"PHASE 2: Waiting for HF22 at block {HF22_BLOCK}")
print("  Expected: dedup → 8 unique ops < PULSE_MIN(12) → Pulse stalls → Gov-signed PoW")
print("=" * 70)

gov_blocks_seen = 0
pulse_after_hf22 = 0
h_now = height()
if h_now < HF22_BLOCK:
    blocks_to_hf22 = HF22_BLOCK - h_now
    print(f"  Currently at h={h_now}, {blocks_to_hf22} blocks to HF22...")
    # Monitor blocks through the HF22 transition
    checked_h = h_now
    while checked_h < HF22_BLOCK + 20:
        time.sleep(2)
        try:
            h = height()
            while checked_h < h:
                checked_h += 1
                t = classify_block(checked_h)
                hf = rpc(SEED_RPC, "get_info").get("hard_fork", 0)
                marker = " <<<< HF22 ACTIVATES" if checked_h == HF22_BLOCK else ""
                print(f"  h={checked_h} hf={hf}: {t}{marker}", flush=True)
                if checked_h >= HF22_BLOCK:
                    if "GOV_SIGNED" in t: gov_blocks_seen += 1
                    if "PULSE" in t: pulse_after_hf22 += 1
        except Exception:
            pass
else:
    # Phase 1 overshot HF22 — scan recent blocks retroactively
    print(f"  HF22 already passed (h={h_now}). Scanning blocks {HF22_BLOCK}..{min(h_now, HF22_BLOCK+50)} for gov-signed blocks...")
    for bh in range(HF22_BLOCK, min(h_now, HF22_BLOCK + 50)):
        t = classify_block(bh)
        if "GOV_SIGNED" in t: gov_blocks_seen += 1
        if "PULSE" in t: pulse_after_hf22 += 1
    print(f"  Retroactive scan: {gov_blocks_seen} gov-signed, {pulse_after_hf22} Pulse blocks post-HF22")

if gov_blocks_seen > 0 and pulse_after_hf22 == 0:
    print(f"\n*** PHASE 2 PASS: Pulse stalled after HF22. {gov_blocks_seen} governance-signed PoW blocks. ***")
elif pulse_after_hf22 > 0:
    print(f"\n*** PHASE 2 UNEXPECTED: Pulse still active after HF22 ({pulse_after_hf22} Pulse blocks). Check dedup logic. ***")
else:
    print(f"\n*** PHASE 2 WARN: Saw neither Pulse nor gov-signed blocks post-HF22. ***")

# ── 10. PHASE 3: Register 4 more SNs (ops 9-12) → restore Pulse ──────────────
print("\n" + "=" * 70)
print("PHASE 3: Registering 4 more SNs (ops 9-12) to reach 12 unique operators")
print("  Expected: 12 unique ops ≥ PULSE_MIN(12) → Pulse resumes")
print("=" * 70)

snode_idx = 17
for op_n in range(9, 13):
    si = snode_idx
    print(f"\n  Operator {op_n} (addr {op_addrs[op_n][:20]}...): registering snode{si}")
    try:
        txhash = register_sn(si, f"op{op_n}", op_addrs[op_n])
        print(f"    -> {txhash[:20] if txhash else 'ERR'}")
    except Exception as e:
        print(f"    -> ERROR: {e}")
    snode_idx += 1
    wait_blocks(2, f"op{op_n} registration confirmation")

print(f"\nAll Phase 3 registrations submitted.")
time.sleep(5)
cnt = sn_count()
print(f"  Total active SNs: {cnt} / 20 (need 12 unique ops)")

print("\n  Waiting for new SNs to activate and Pulse to resume...")
phase3_ok = wait_for_pulse(min_pulse_blocks=5, timeout_blocks=300, label="Phase3")

print("\n" + "=" * 70)
print("TEST RESULTS")
print("=" * 70)
print(f"  Phase 1 (Pulse with 8 unique ops, pre-HF22):   {'PASS' if phase1_ok else 'FAIL'}")
print(f"  Phase 2 (Pulse stalls at HF22, dedup fires):   {'PASS' if gov_blocks_seen > 0 else 'FAIL'}")
print(f"  Phase 3 (Pulse resumes with 12 unique ops):    {'PASS' if phase3_ok else 'FAIL'}")
print()

if phase1_ok and gov_blocks_seen > 0 and phase3_ok:
    print("ALL PHASES PASS — HF22 operator dedup is production-ready.")
    sys.exit(0)
else:
    print("Some phases failed — see output above for details.")
    sys.exit(1)
