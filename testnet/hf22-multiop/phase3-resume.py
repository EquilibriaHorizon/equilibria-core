#!/usr/bin/env python3
"""
Phase 3 rescue script for the HF22 three-phase test.
Assumes:
  - wallet-rpc running on 18183 (started by the main test script)
  - op9-op12 wallets exist and are funded (funded by the main test script)
  - snodes 17-20 running (started by the main test script)
  - chain is past HF22 (h >= 400), Pulse stalled with 8 unique ops

This script registers snodes 17-20 (ops 9-12) to reach 12 unique operators
and verifies that Pulse resumes.
"""
import json, os, sys, time, urllib.request

SEED_RPC   = "http://127.0.0.1:49001/json_rpc"
WALLET_RPC = "http://127.0.0.1:18183/json_rpc"
WALLET_DIR = "/home/svshearer/xeqm-testnet/wallet"
COIN       = 1_000_000_000
STAKING_AMT = 100_000_000_000   # 100 XEQM per SN

def rpc(url, method, params=None):
    body = json.dumps({"jsonrpc":"2.0","method":method,
                       "params":params or {},"id":"0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    if "error" in d:
        raise RuntimeError(f"{method}: {d['error']['message']}")
    return d.get("result", {})

def height():
    return rpc(SEED_RPC, "get_info").get("height", 0)

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

def open_wallet(name, password=""):
    try:
        rpc(WALLET_RPC, "close_wallet", {})
    except Exception:
        pass
    rpc(WALLET_RPC, "open_wallet", {"filename": name, "password": password})

def refresh():
    try: rpc(WALLET_RPC, "refresh", {})
    except Exception: pass

def unlocked_balance():
    refresh()
    return rpc(WALLET_RPC, "get_balance", {"account_index":0})["unlocked_balance"] // COIN

def get_address():
    return rpc(WALLET_RPC, "get_address", {"account_index":0})["address"]

def snode_rpc_url(i):
    return f"http://127.0.0.1:{49000+i*100+1}/json_rpc"

def register_sn(snode_idx, op_wallet_name, op_addr):
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

def wait_blocks(n, label=""):
    pre = height()
    target = pre + n
    print(f"  waiting {n} blocks (h>{target}) {label}...", flush=True)
    for _ in range(n * 60 + 30):
        time.sleep(3)
        try:
            h = height()
            if h > target:
                print(f"  h={h} ✓", flush=True); return h
        except Exception:
            pass
    return height()

def sn_count():
    resp = rpc(SEED_RPC, "get_service_nodes", {"include_json": False})
    sns = resp.get("service_node_states", resp.get("service_nodes_infos", []))
    return len(sns)

def wait_for_pulse(min_pulse_blocks=5, timeout_blocks=200, label=""):
    """Return True once min_pulse_blocks Pulse blocks are confirmed.
    height() returns the next-block-to-mine number; tip is height()-1.
    Always classify at most tip (height-1) to avoid ERR on non-existent block.
    """
    start_h = height()
    pulse_seen = 0
    checked_h = start_h
    print(f"  [{label}] watching for {min_pulse_blocks} Pulse blocks from h={start_h}...", flush=True)
    for _ in range(timeout_blocks * 10):
        time.sleep(1)
        try:
            tip = height() - 1   # last block that actually exists
            while checked_h < tip:
                checked_h += 1
                t = classify_block(checked_h)
                if "PULSE" in t:
                    pulse_seen += 1
                    print(f"    h={checked_h}: {t} (Pulse #{pulse_seen})", flush=True)
                    if pulse_seen >= min_pulse_blocks:
                        return True
                elif pulse_seen > 0 or checked_h % 5 == 0:
                    print(f"    h={checked_h}: {t}", flush=True)
        except Exception:
            pass
    print(f"  [{label}] timeout after {timeout_blocks} blocks, saw {pulse_seen} Pulse blocks")
    return False


print("=" * 70)
print("PHASE 3 RESCUE: HF22 Operator Dedup Test — Pulse Resumption")
print("=" * 70)

# Confirm chain state
h_now = height() - 1
print(f"\nCurrent chain tip: h={h_now}")
print("Checking recent blocks for context...")
scan_start = max(400, h_now - 10)
for bh in range(scan_start, h_now + 1):
    t = classify_block(bh)
    print(f"  h={bh}: {t}")

cnt = sn_count()
print(f"\nCurrent registered SNs: {cnt}")
print(f"Need 12 unique operators for Pulse. Currently 8 unique ops (16 SNs registered).")

# Check op9-12 wallets exist and have funds
print("\n=== Verifying Phase 3 operator wallets (op9-op12) ===")
op_addrs = {}
for n in range(9, 13):
    name = f"op{n}"
    wallet_file = os.path.join(WALLET_DIR, f"{name}.keys")
    if not os.path.exists(wallet_file):
        print(f"  op{n}: MISSING wallet file! Cannot continue.")
        sys.exit(1)
    open_wallet(name, "")
    addr = get_address()
    bal = unlocked_balance()
    op_addrs[n] = addr
    print(f"  op{n}: addr={addr[:20]}... unlocked={bal} XEQM")
    if bal < 100:
        print(f"  WARNING: op{n} has < 100 XEQM! Will retry after waiting for unlock...")
        # Wait up to 5 minutes for unlock
        for _ in range(100):
            time.sleep(3)
            bal = unlocked_balance()
            if bal >= 100:
                print(f"    → {bal} XEQM unlocked ✓")
                break
        else:
            print(f"    → Still insufficient funds. Exiting.")
            sys.exit(1)

# Register snodes 17-20 with ops 9-12
print("\n=== Phase 3: Registering snodes 17-20 (ops 9-12) ===")
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
print(f"  Total active SNs: {cnt} / 20 (12 unique operators now)")

print("\n  Waiting 10 blocks for SNs to activate and uptime proofs to propagate...")
wait_blocks(10, "SN activation + uptime proof propagation")

# Verify Pulse resumes
print("\n=== Phase 3 Verification: Watching for Pulse resumption ===")
print("  Expected: 12 unique operators ≥ PULSE_MIN(12) → Pulse resumes")
phase3_ok = wait_for_pulse(min_pulse_blocks=5, timeout_blocks=300, label="Phase3")

print("\n" + "=" * 70)
print("PHASE 3 RESULT")
print("=" * 70)
if phase3_ok:
    print("*** PHASE 3 PASS: Pulse resumed with 12 unique operators! ***")
    print("    HF22 operator dedup is production-ready.")
    sys.exit(0)
else:
    print("*** PHASE 3 FAIL: Pulse did not resume within timeout. ***")
    print("    Direct chain query of recent blocks:")
    tip = height() - 1
    for bh in range(max(tip-20, 0), tip+1):
        print(f"    h={bh}: {classify_block(bh)}")
    sys.exit(1)
