#!/usr/bin/env python3
"""Full testnet setup: start daemons, restore wallet, mine funds, register 20 SNs."""
import json, subprocess, time, urllib.request, sys, os

SEED_RPC    = "http://127.0.0.1:49001/json_rpc"
WALLET_RPC  = "http://127.0.0.1:18183/json_rpc"
WALLET_DIR  = "/home/svshearer/xeqm-testnet/wallet"
WALLET_NAME = "testnet-gov"
WALLET_PASS = "xeqm-testnet"
XEQM_RPC   = "/home/svshearer/xeqm-core/build/bin/xeqm-rpc"
NUM_SNODES  = 20
STAKING_AMT = 100_000_000_000   # 100 XEQM per SN
COIN        = 1_000_000_000
# Wait for enough XEQM unlocked: 20×100 + 2000 buffer.
# Each governance batch output is ~103.25 XEQM. With ring size=11 decoys,
# we need enough outputs for decoy selection across all 20 registrations.
# 4000 XEQM → ~38 unlocked governance outputs → ample decoy pool.
WAIT_FOR_XEQM = 1800

# Fixed governance wallet keys (testnet-only, NOT mainnet keys).
# These match GOVERNANCE_WALLET_ADDRESS[0] in src/network_config/testnet.h.
# Option A uses the governance spend key to sign fallback miner blocks.
GOV_ADDRESS   = "XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx"
GOV_VIEW_KEY  = "8e34dd7f6eb9b9f28be81619e20765c53b79070aab49c353ffc877b67389cd09"
GOV_SPEND_KEY = "0c999a88be252215b48735272e5cf3dd86d54f850bb0bc8bfe9aea0de7549405"

def rpc(url, method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "method": method,
                       "params": params or {}, "id": "0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    if "error" in d:
        raise RuntimeError(f"{method}: {d['error']['message']}")
    return d.get("result", {})

def wait_for_rpc(url, label, timeout=60):
    for _ in range(timeout // 2):
        try:
            rpc(url, "get_info" if "49001" in url else "get_version")
            print(f"  {label} ready")
            return True
        except Exception:
            time.sleep(2)
    print(f"  {label} timed out!")
    return False

def wait_for_block(target_height, label="next block", timeout_blocks=30):
    """Poll until chain height exceeds target_height. Returns new height."""
    pre = rpc(SEED_RPC, "get_info").get("height", 0)
    if target_height == 0:
        target_height = pre
    print(f"  --- {label}: waiting for h>{target_height} ---", flush=True)
    for _ in range(timeout_blocks * 10):   # 10 polls per expected block
        time.sleep(1)
        try:
            h = rpc(SEED_RPC, "get_info").get("height", 0)
            if h > target_height:
                print(f"  --- block confirmed at h={h} ---", flush=True)
                return h
        except Exception:
            pass
    print(f"  --- WARNING: timed out waiting for h>{target_height} ---")
    return target_height

# ── 1. Wallet-rpc: kill stale process, start fresh ───────────────────────────
PID_DIR  = "/home/svshearer/xeqm-testnet/pids"
LOG_DIR  = "/home/svshearer/xeqm-testnet/logs"
DATA_DIR = "/home/svshearer/xeqm-testnet/data"
os.makedirs(PID_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(WALLET_DIR, exist_ok=True)

pid_file = f"{PID_DIR}/wallet-rpc.pid"
# Kill any existing wallet-rpc to release wallet file locks
try:
    old_pid = int(open(pid_file).read().strip())
    if os.path.exists(f"/proc/{old_pid}"):
        print(f"Stopping old wallet-rpc (pid {old_pid})...")
        os.kill(old_pid, 15)
        time.sleep(2)
    os.remove(pid_file)
except Exception:
    pass

print("Starting wallet-rpc...")
log = open(f"{LOG_DIR}/wallet-rpc.log", "a")
proc = subprocess.Popen([
    XEQM_RPC, "--testnet",
    "--wallet-dir", WALLET_DIR,
    "--rpc-bind-port", "18183",
    "--daemon-address", "127.0.0.1:49001",
    "--disable-rpc-login", "--log-level", "0",
], stdout=log, stderr=log, preexec_fn=os.setsid)
open(pid_file, "w").write(str(proc.pid))
print(f"  wallet-rpc pid {proc.pid}")
wait_for_rpc(WALLET_RPC, "wallet-rpc")

# ── 2. Wallet: restore fresh from keys if no wallet file; open if resuming ────
# The wallet ring DB (keyed by key image) must NOT persist across testnet resets.
# After a chain wipe the governance TX pubkeys differ, yielding different key images.
# Stale ring DB entries matching the new key images cause:
#   "Known ring does not include the spent output: N"
# reset-testnet.sh deletes the wallet files; this path then creates a clean wallet.
wallet_keys_file = os.path.join(WALLET_DIR, f"{WALLET_NAME}.keys")
if os.path.exists(wallet_keys_file):
    print("Wallet file exists — opening (resuming run)...")
    rpc(WALLET_RPC, "open_wallet", {"filename": WALLET_NAME, "password": WALLET_PASS})
    print("  wallet opened")
else:
    print("No wallet file — restoring fresh from governance keys (clean ring DB)...")
    rpc(WALLET_RPC, "generate_from_keys", {
        "filename": WALLET_NAME,
        "password": WALLET_PASS,
        "address": GOV_ADDRESS,
        "viewkey": GOV_VIEW_KEY,
        "spendkey": GOV_SPEND_KEY,
        "restore_height": 0,
    })
    print("  wallet restored")

addr_info = rpc(WALLET_RPC, "get_address", {"account_index": 0})
WALLET_ADDR = addr_info["address"]
print(f"Wallet address: {WALLET_ADDR}")
open(os.path.join(WALLET_DIR, "address.txt"), "w").write(WALLET_ADDR)

# ── 3. Launch seed + 20 SNs ──────────────────────────────────────────────────
xeqmd = "/home/svshearer/xeqm-core/build/bin/xeqm-d"

def start_daemon(name, args):
    pf = f"{PID_DIR}/{name}.pid"
    try:
        pid = int(open(pf).read().strip())
        os.kill(pid, 0)
        print(f"  [{name}] already running (pid {pid})")
        return
    except Exception:
        pass
    os.makedirs(f"{DATA_DIR}/{name}", exist_ok=True)
    lg = open(f"{LOG_DIR}/{name}.log", "a")
    p = subprocess.Popen(
        [xeqmd, "--testnet", "--non-interactive",
         f"--data-dir={DATA_DIR}/{name}"] + args,
        stdout=lg, stderr=lg, preexec_fn=os.setsid)
    open(pf, "w").write(str(p.pid))
    print(f"  [{name}] started pid {p.pid}")

# Kill old seed (it may lack --fallback-miner-key if started by start-testnet.sh)
seed_pid_file = f"{PID_DIR}/seed.pid"
try:
    old_pid = int(open(seed_pid_file).read().strip())
    os.kill(old_pid, 15)
    time.sleep(2)
    os.remove(seed_pid_file)
    print("Stopped old seed.")
except Exception:
    pass

# Option A: seed signs fallback miner blocks with the governance spend key.
FALLBACK_MINER_KEY = GOV_SPEND_KEY

print("Starting seed (mining to governance wallet)...")
start_daemon("seed", [
    "--p2p-bind-ip=0.0.0.0", "--p2p-bind-port=49000",
    "--rpc-admin=127.0.0.1:49001",
    "--start-mining", WALLET_ADDR, "--mining-threads", "2",
    "--fallback-miner-key", FALLBACK_MINER_KEY,
])

print("Waiting for seed RPC...")
wait_for_rpc(SEED_RPC, "seed")

# Port layout: snode N → p2p=49000+N*100, rpc=p2p+1, qnet=p2p+2
# snode01: 49100/49101/49102 ... snode20: 51000/51001/51002
print(f"Starting {NUM_SNODES} snode daemons...")
for i in range(1, NUM_SNODES + 1):
    p2p  = 49000 + i * 100
    rpc_ = p2p + 1
    qnet = p2p + 2
    # snode1 gets pulse:info so Pulse rounds are visible in its log.
    extra = ["--log-level", "pulse:info"] if i == 1 else []
    start_daemon(f"snode{i}", [
        "--service-node", "--dev-allow-local-ips",
        "--p2p-bind-ip=0.0.0.0", f"--p2p-bind-port={p2p}",
        f"--rpc-admin=127.0.0.1:{rpc_}",
        f"--quorumnet-port={qnet}",
        "--service-node-public-ip=127.0.0.1",
        "--seed-node=127.0.0.1:49000",
        "--add-priority-node=127.0.0.1:49000",
    ] + extra)
print(f"All {NUM_SNODES} snode daemons launched.")

# The seed needs at least one peer before is_synchronized() returns true.
# Once a snode connects, mining may auto-start; if not, start it via RPC.
print("Waiting for mining to become active (snodes provide the required peer)...")
for _ in range(30):
    time.sleep(3)
    try:
        ms = rpc(SEED_RPC, "mining_status")
        if ms.get("active"):
            print(f"  Mining active @ {ms.get('speed',0)} h/s")
            break
        # Kick it manually — needed when --start-mining auto-start is blocked by BUSY
        rpc(SEED_RPC, "start_mining", {
            "miner_address": WALLET_ADDR,
            "threads_count": 2,
        })
    except Exception:
        pass
else:
    print("  WARNING: mining may not be active — continuing anyway")

# ── 4. Wait for HF19 and enough balance to stake all 20 SNs ──────────────────
print(f"Waiting for HF19 (block 9) and {WAIT_FOR_XEQM} XEQM unlocked (up to 90 min)...")
for poll in range(1080):
    time.sleep(5)
    try:
        info = rpc(SEED_RPC, "get_info")
        hf = info.get("hard_fork", 0)
        height = info.get("height", 0)
        rpc(WALLET_RPC, "refresh", {})
        bal = rpc(WALLET_RPC, "get_balance", {"account_index": 0})
        unlocked = bal["unlocked_balance"] // COIN
        if poll % 12 == 0 or unlocked >= WAIT_FOR_XEQM:
            print(f"  height={height} hf={hf} unlocked={unlocked} XEQM (need {WAIT_FOR_XEQM})")
        if hf >= 19 and unlocked >= WAIT_FOR_XEQM:
            print(f"  Ready to register at h={height}!")
            break
    except Exception as e:
        print(f"  [{poll}] polling... ({e})")
else:
    print("Timed out waiting for funds/HF19")
    sys.exit(1)

# ── 5. Register all 20 SNs ───────────────────────────────────────────────────
# Register in batches of 5 with a 2-block confirmation wait between batches.
# Key ring integrity: wallet is freshly restored from keys on each testnet reset,
# so it has no stale ring DB entries. The 2-block wait ensures batch N's txs are
# mined before batch N+1 selects ring members, avoiding mempool-decoy conflicts.
BATCH_SIZE = 5

print(f"\n=== Registering {NUM_SNODES} SNs (100 XEQM each, 10% fee, batch={BATCH_SIZE}) ===")
registered = 0
failed = []
for i in range(1, NUM_SNODES + 1):
    snode_rpc = f"http://127.0.0.1:{49000 + i * 100 + 1}/json_rpc"
    print(f"  snode{i:02d} -> ", end="", flush=True)
    try:
        rpc(WALLET_RPC, "refresh", {})
    except Exception:
        pass
    try:
        resp = rpc(snode_rpc, "get_service_node_registration_cmd", {
            "operator_cut": "10",
            "contributor_addresses": [WALLET_ADDR],
            "contributor_amounts": [STAKING_AMT],
            "staking_requirement": STAKING_AMT,
        })
        reg_cmd = resp.get("registration_cmd", "")
        if not reg_cmd:
            print("empty reg_cmd"); failed.append(i); continue
        relay = rpc(WALLET_RPC, "register_service_node",
                    {"register_service_node_str": reg_cmd})
        print(relay.get("tx_hash", "no-txid"))
        registered += 1
    except Exception as e:
        print(f"ERROR: {e}")
        failed.append(i)
        continue

    if i % BATCH_SIZE == 0 and i < NUM_SNODES:
        # Wait for 2 blocks so all batch txs are confirmed before the next batch
        cur = rpc(SEED_RPC, "get_info").get("height", 0)
        h1 = wait_for_block(cur, f"batch {i // BATCH_SIZE} block 1")
        rpc(WALLET_RPC, "refresh", {})
        wait_for_block(h1, f"batch {i // BATCH_SIZE} block 2")
        rpc(WALLET_RPC, "refresh", {})
    else:
        time.sleep(1)

print(f"\nRegistered: {registered} / {NUM_SNODES}")
if failed:
    print(f"Failed snodes: {failed}")
    sys.exit(1)
else:
    print("All SNs registered successfully.")
print("HF22 fires at block 250 — run monitor-pulse.sh to watch the Pulse → GOV_SIGNED transition")
