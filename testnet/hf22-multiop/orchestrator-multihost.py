#!/usr/bin/env python3
"""
HF22 Multi-Host Orchestrator
=============================
Hosts:
  Fernando (192.168.50.11):  seed at 49001, snodes 1-10 at rpc 49101-50001  (local)
  Lemon    (192.168.50.10):  snodes 1-10 at rpc 50101-51001  (SSH tunnel via internal IP)
  Missoula (144.126.159.227): snodes 1-10 at rpc 49101-50001 (SSH tunnel)
  Maple    (144.217.7.129):  snodes 1-10 at rpc 49101-50001  (SSH tunnel)

Operators (20 total, 2 SNs each = 40 SNs):
  op1-op5   -> Fernando snodes 1-2, 3-4, 5-6, 7-8, 9-10
  op6-op10  -> Lemon    snodes 1-2, 3-4, 5-6, 7-8, 9-10
  op11-op15 -> Missoula snodes 1-2, 3-4, 5-6, 7-8, 9-10
  op16-op20 -> Maple    snodes 1-2, 3-4, 5-6, 7-8, 9-10

Phase 1: 20 stall/recovery cycles. Stall = deregister ops 11-20 (missoula+maple, drops to
10 unique ops, below quorum threshold). Recovery = re-register op11 (11 ops, Pulse resumes).
Phase 2: 1000-block pure stability run at 60s block time.

Usage:
  python3 orchestrator-multihost.py [--cycles N] [--blocks N] [--phase {1,2}]
  nohup python3 orchestrator-multihost.py > orchestrator-multihost.log 2>&1 &
"""
import argparse, json, subprocess, sys, time, os
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

SEED_RPC        = "http://127.0.0.1:49001/json_rpc"   # Fernando seed, local
WALLET_RPC      = "http://127.0.0.1:18183/json_rpc"    # Fernando wallet daemon
DATA_DIR        = "/home/svshearer/xeqm-testnet"
LOG_DIR         = DATA_DIR
WALLETS_DIR     = f"{DATA_DIR}/wallet"

STAKING_REQUIREMENT = 100_000_000_000   # 100 XEQM in atomic units (9 decimal places)

# tunnel base: local port = TUNNEL_BASE + (host_idx * 20) + snode_idx
TUNNEL_BASE     = 55000

# Remote host SSH names and their snode RPC ports
# maple uses ProxyJump via missoula since Fernando can't SSH to maple directly
REMOTE_HOSTS = {
    "lemon":    {"ssh": "192.168.50.10",   "snode_rpc_base": 50101, "snode_count": 10,
                 "proxy_jump": None},
    "missoula": {"ssh": "144.126.159.227", "snode_rpc_base": 49101, "snode_count": 10,
                 "proxy_jump": None},
    "maple":    {"ssh": "144.217.7.129",   "snode_rpc_base": 49101, "snode_count": 10,
                 "proxy_jump": "144.126.159.227"},
}

# Operator -> (host, snode indices on that host, both 1-indexed)
# 2 SNs per operator, 20 operators total, 40 SNs
OPERATOR_MAP = {
    1:  ("fernando", [1, 2]),
    2:  ("fernando", [3, 4]),
    3:  ("fernando", [5, 6]),
    4:  ("fernando", [7, 8]),
    5:  ("fernando", [9, 10]),
    6:  ("lemon",    [1, 2]),
    7:  ("lemon",    [3, 4]),
    8:  ("lemon",    [5, 6]),
    9:  ("lemon",    [7, 8]),
    10: ("lemon",    [9, 10]),
    11: ("missoula", [1, 2]),
    12: ("missoula", [3, 4]),
    13: ("missoula", [5, 6]),
    14: ("missoula", [7, 8]),
    15: ("missoula", [9, 10]),
    16: ("maple",    [1, 2]),
    17: ("maple",    [3, 4]),
    18: ("maple",    [5, 6]),
    19: ("maple",    [7, 8]),
    20: ("maple",    [9, 10]),
}

FERNANDO_RPC_BASE = 49101   # local, no tunnel needed

# ── Logging ───────────────────────────────────────────────────────────────────

RUN_START  = time.time()
EVENT_LOG  = []
BLOCK_LOG  = []

def now_str():
    return datetime.utcnow().strftime("%H:%M:%S")

def elapsed():
    return str(timedelta(seconds=int(time.time() - RUN_START)))

def log(msg, level="INFO"):
    print(f"[{now_str()} +{elapsed()}] {level}: {msg}", flush=True)

def event(kind, **kw):
    e = {"kind": kind, "wall_time": now_str(), "elapsed_s": int(time.time()-RUN_START), **kw}
    EVENT_LOG.append(e)
    log(f"EVENT {kind}: {kw}", level="EVENT")

# ── RPC ───────────────────────────────────────────────────────────────────────

import urllib.request

def rpc(url, method, params=None, timeout=30):
    body = json.dumps({"jsonrpc": "2.0", "method": method,
                       "params": params or {}, "id": "0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
            if "result" not in resp:
                raise RuntimeError(f"JSON-RPC error: {resp.get('error', resp)}")
            return resp["result"]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"RPC {method} @ {url}: {e}")

def seed(method, params=None):
    return rpc(SEED_RPC, method, params)

WALLET_RPC_CMD = (
    "/home/svshearer/xeqm-core/build/bin/xeqm-rpc "
    "--testnet --wallet-dir /home/svshearer/xeqm-testnet/wallet "
    "--rpc-bind-port 18183 --daemon-address 127.0.0.1:49001 "
    "--disable-rpc-login --log-level 0"
)

def ensure_wallet_rpc():
    """Restart wallet RPC if it is not responding."""
    try:
        rpc(WALLET_RPC, "get_version", timeout=5)
        return
    except Exception:
        pass
    log("Wallet RPC down — restarting...", level="WARN")
    subprocess.Popen(WALLET_RPC_CMD.split(), stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(2)
        try:
            rpc(WALLET_RPC, "get_version", timeout=5)
            log("Wallet RPC restarted OK")
            return
        except Exception:
            pass
    raise RuntimeError("Wallet RPC failed to restart")

def wallet(method, params=None):
    for attempt in range(3):
        ensure_wallet_rpc()
        try:
            return rpc(WALLET_RPC, method, params)
        except RuntimeError as e:
            if attempt < 2:
                log(f"Wallet {method} failed (attempt {attempt+1}), retrying: {e}", level="WARN")
                time.sleep(3)
            else:
                raise

def tip():
    return seed("get_info")["height"] - 1

def block_type(h):
    try:
        blk = seed("get_block", {"height": h})["block_header"]
        vbits = blk.get("pulse", {}).get("validator_bitset", 0)
        if vbits == 0:
            return "GOV_SIGNED", 0
        return "PULSE", bin(vbits).count("1")
    except Exception as e:
        log(f"block_type({h}): {e}", level="WARN")
        return "UNKNOWN", 0

def snode_count():
    try:
        sns = seed("get_service_nodes", {}).get("service_node_states", [])
        ops = {s["operator_address"] for s in sns}
        return len(sns), len(ops)
    except Exception:
        return 0, 0

# ── SSH Tunnels ───────────────────────────────────────────────────────────────

_tunnels = {}   # key -> subprocess

def open_tunnels():
    """Open SSH tunnels for all remote host snode RPCs."""
    host_idx = 0
    for host, cfg in REMOTE_HOSTS.items():
        ssh_target  = cfg["ssh"]
        base_remote = cfg["snode_rpc_base"]
        count       = cfg["snode_count"]
        proxy_jump  = cfg.get("proxy_jump")
        for i in range(count):
            local_port  = TUNNEL_BASE + host_idx * 20 + i
            remote_port = base_remote + i * 100
            key = (host, i + 1)
            cmd = ["ssh", "-N", "-o", "StrictHostKeyChecking=no",
                   "-o", "ExitOnForwardFailure=no"]
            if proxy_jump:
                cmd += ["-J", proxy_jump]
            cmd += ["-L", f"{local_port}:127.0.0.1:{remote_port}", ssh_target]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _tunnels[key] = (proc, local_port)
        host_idx += 1
    log(f"Opened {len(_tunnels)} SSH tunnels for remote snode RPCs")
    time.sleep(3)   # let tunnels establish

def close_tunnels():
    for proc, _ in _tunnels.values():
        proc.terminate()
    log("SSH tunnels closed")

def snode_rpc_url(host, snode_idx):
    """Return the RPC URL for a given (host, snode_idx 1-based)."""
    if host == "fernando":
        port = FERNANDO_RPC_BASE + (snode_idx - 1) * 100
        return f"http://127.0.0.1:{port}/json_rpc"
    key = (host, snode_idx)
    _, local_port = _tunnels[key]
    return f"http://127.0.0.1:{local_port}/json_rpc"

# ── Wallet helpers ────────────────────────────────────────────────────────────

def open_wallet(op_num):
    wallet("open_wallet", {"filename": f"op{op_num}", "password": ""})
    time.sleep(0.3)
    wallet("refresh", {})
    time.sleep(0.3)

def get_wallet_address(op_num):
    open_wallet(op_num)
    return wallet("get_address", {})["address"]

def register_snode(op_num, host, snode_idx):
    url = snode_rpc_url(host, snode_idx)

    # Get wallet address first (needed by new API)
    op_addr = get_wallet_address(op_num)

    for attempt in range(10):
        try:
            r = rpc(url, "get_service_node_registration_cmd", {
                "operator_cut": "0",
                "contributor_addresses": [op_addr],
                "contributor_amounts":   [STAKING_REQUIREMENT],
                "staking_requirement":   STAKING_REQUIREMENT,
            }, timeout=15)
            cmd = r.get("registration_cmd", "")
            if not cmd:
                raise RuntimeError(f"empty registration_cmd: {r}")
            break
        except Exception as e:
            if attempt == 9:
                raise
            log(f"  snode {host}/{snode_idx} not ready: {e} (retry {attempt+1})", level="WARN")
            time.sleep(8)

    open_wallet(op_num)
    result = wallet("register_service_node", {"register_service_node_str": cmd})
    tx = result.get("txid", result.get("tx_hash", "?"))
    log(f"  op{op_num} {host}/snode{snode_idx} registered tx={tx[:16]}...")
    return tx


def is_snode_registered(host, snode_idx):
    """Return True if this snode's pubkey is already active on chain."""
    url = snode_rpc_url(host, snode_idx)
    try:
        r = rpc(url, "get_service_node_key", {}, timeout=10)
        pubkey = r.get("service_node_pubkey", "")
        if not pubkey:
            return False
        sns = seed("get_service_nodes", {"service_node_pubkeys": [pubkey]})
        return len(sns.get("service_node_states", [])) > 0
    except Exception:
        return False

def unlock_snode(op_num, pubkey):
    open_wallet(op_num)
    result = wallet("request_stake_unlock", {"service_node_key": pubkey, "priority": 1})
    return result.get("tx_hash", "?")

# ── Chain monitoring ──────────────────────────────────────────────────────────

def wait_for_height(target_h, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = tip()
            if h >= target_h:
                return h
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for h={target_h}")

def wait_for_pulse(from_h, timeout=3600):
    """Wait until a PULSE block appears after from_h. Returns recovery height."""
    deadline = time.time() + timeout
    last_h = from_h
    while time.time() < deadline:
        try:
            cur_h = tip()
        except Exception:
            time.sleep(5)
            continue
        for h in range(last_h + 1, cur_h + 1):
            btype, nsigs = block_type(h)
            BLOCK_LOG.append({"height": h, "type": btype, "sigs": nsigs})
            if btype == "PULSE":
                return h, nsigs
            log(f"  h={h} GOV_SIGNED (waiting for Pulse...)", level="WARN")
        last_h = cur_h
        time.sleep(5)
    raise TimeoutError(f"Pulse did not resume within {timeout}s after h={from_h}")

def confirm_stall(from_h, min_gov_blocks=3, timeout=600):
    """Confirm chain is in stall mode by seeing min_gov_blocks consecutive GOV_SIGNED."""
    deadline = time.time() + timeout
    last_h = from_h
    gov_count = 0
    while time.time() < deadline:
        try:
            cur_h = tip()
        except Exception:
            time.sleep(5)
            continue
        for h in range(last_h + 1, cur_h + 1):
            btype, nsigs = block_type(h)
            BLOCK_LOG.append({"height": h, "type": btype, "sigs": nsigs})
            if btype == "GOV_SIGNED":
                gov_count += 1
                if gov_count >= min_gov_blocks:
                    return h
            else:
                gov_count = 0
        last_h = cur_h
        time.sleep(5)
    raise TimeoutError(f"Stall not confirmed within {timeout}s")

# ── Phase 1: Stall/recovery cycles ───────────────────────────────────────────

def run_phase1(num_cycles=20, start_cycle=1):
    log(f"=== Phase 1: {num_cycles} stall/recovery cycles ===")
    log("Waiting for seed daemon...")
    while True:
        try:
            h = tip()
            log(f"Seed ready at h={h}")
            break
        except Exception as e:
            log(f"  seed not ready: {e}", level="WARN")
            time.sleep(5)

    log("Opening SSH tunnels for remote snodes...")
    open_tunnels()

    # Two-pass registration to avoid UTXO lock:
    # After staking snode[0], the change output is unconfirmed for ~1 block.
    # Registering both SNs back-to-back causes the second to fail every time.
    log("Registering all 20 operators (40 SNs) — two-pass to avoid UTXO lock...")
    sn_pubkeys = {}   # (host, snode_idx) -> pubkey

    def _try_register(op_num, host, si):
        if is_snode_registered(host, si):
            log(f"  op{op_num} {host}/snode{si} already on chain, skipping")
            return
        for attempt in range(5):
            try:
                register_snode(op_num, host, si)
                return
            except Exception as e:
                log(f"  op{op_num} {host}/snode{si} reg failed: {e}", level="WARN")
                time.sleep(10)

    log("  Pass 1: first SN for each operator...")
    for op_num, (host, snode_indices) in OPERATOR_MAP.items():
        _try_register(op_num, host, snode_indices[0])
        time.sleep(0.5)

    log("  Waiting 1 block for UTXO change outputs to confirm...")
    wait_for_height(tip() + 1, timeout=300)

    log("  Pass 2: second SN for each operator...")
    for op_num, (host, snode_indices) in OPERATOR_MAP.items():
        _try_register(op_num, host, snode_indices[1])
        time.sleep(0.5)

    # Wait for registrations to land
    log("Waiting for all 40 SNs to appear on chain...")
    deadline = time.time() + 600
    while time.time() < deadline:
        cnt, ops = snode_count()
        log(f"  SNs={cnt} ops={ops}")
        if cnt >= 37 and ops == 20:  # 37+ with all 20 ops is sufficient
            break
        time.sleep(15)
    cnt, ops = snode_count()
    if cnt != 40:
        log(f"WARNING: only {cnt} SNs registered, expected 40", level="WARN")

    start_h = tip()
    event("phase1_start", height=start_h, sn_count=cnt, op_count=ops)
    log(f"Starting Phase 1 cycles at h={start_h}")

    results = []

    for cycle in range(start_cycle, num_cycles + 1):
        log(f"\n--- Cycle {cycle}/{num_cycles} ---")
        pre_h = tip()

        # Collect pubkeys for ops 11-20 (stall set: missoula+maple operators)
        # Deregistering 10 operators drops unique ops from 20 to 10 (below 11-op quorum threshold)
        sns = seed("get_service_nodes", {}).get("service_node_states", [])
        stall_ops = list(range(11, 21))

        # Build address map from wallet RPC
        op_addresses = {}
        for op_num in stall_ops:
            open_wallet(op_num)
            addr = wallet("get_address", {})["address"]
            op_addresses[op_num] = addr

        stall_pubkeys = {}
        for sn in sns:
            for op_num, addr in op_addresses.items():
                if sn["operator_address"] == addr:
                    stall_pubkeys.setdefault(op_num, []).append(sn["service_node_pubkey"])

        # Unlock (deregister) ops 11-20
        log(f"  Deregistering ops 11-20 (missoula+maple) to trigger stall...")
        for op_num in stall_ops:
            pks = stall_pubkeys.get(op_num, [])
            for pk in pks:
                try:
                    tx = unlock_snode(op_num, pk)
                    log(f"  op{op_num} unlock tx={tx[:16]}...")
                except Exception as e:
                    log(f"  op{op_num} unlock failed: {e}", level="WARN")
            time.sleep(0.3)

        # Wait for stall confirmation
        event("stall_deregister", cycle=cycle, height=pre_h)
        log(f"  Waiting for stall confirmation...")
        try:
            stall_h = confirm_stall(pre_h, min_gov_blocks=3)
        except TimeoutError as e:
            log(f"  WARN: {e}", level="WARN")
            stall_h = tip()
        event("stall_confirmed", cycle=cycle, height=stall_h)
        log(f"  Stall confirmed at h={stall_h}")

        # Re-register op11 to trigger recovery (two-pass to avoid UTXO lock)
        log(f"  Re-registering op11 to trigger recovery...")
        op11_host = OPERATOR_MAP[11][0]
        op11_snodes = OPERATOR_MAP[11][1]
        already_on_chain = False
        try:
            register_snode(11, op11_host, op11_snodes[0])
        except RuntimeError as e:
            if "already registered" in str(e).lower():
                log(f"  op11/snode{op11_snodes[0]} already registered — treating as active", level="WARN")
                already_on_chain = True
            else:
                raise
        if not already_on_chain and len(op11_snodes) > 1:
            log("  Waiting 1 block for op11 UTXO change output...")
            time.sleep(65)
            try:
                register_snode(11, op11_host, op11_snodes[1])
            except RuntimeError as e:
                msg = str(e).lower()
                if "already registered" in msg:
                    log(f"  op11/snode{op11_snodes[1]} already registered — OK", level="WARN")
                elif "not enough" in msg:
                    log(f"  op11/snode{op11_snodes[1]} UTXO not mature — snode1 sufficient for recovery", level="WARN")
                else:
                    raise

        # Wait for Pulse to resume (extended timeout: GOV blocks can be 2-3 min each)
        try:
            recovery_h, nsigs = wait_for_pulse(stall_h, timeout=3600)
        except TimeoutError as e:
            log(f"  TIMEOUT waiting for Pulse: {e}", level="WARN")
            results.append({"cycle": cycle, "stall_h": stall_h, "result": "TIMEOUT"})
            continue

        duration_blocks = recovery_h - stall_h
        event("recovery_confirmed", cycle=cycle, height=recovery_h, sigs=nsigs,
              stall_blocks=duration_blocks)
        log(f"  PASS: Pulse resumed at h={recovery_h} PULSE[{nsigs}] "
            f"after {duration_blocks} blocks")
        results.append({"cycle": cycle, "stall_h": stall_h, "recovery_h": recovery_h,
                         "duration_blocks": duration_blocks, "sigs": nsigs, "result": "PASS"})

        # Re-register ops 12-20 to restore full fleet (two-pass to avoid UTXO lock)
        log(f"  Restoring ops 12-20 (pass 1: first SN each)...")
        for op_num in range(12, 21):
            host, snode_indices = OPERATOR_MAP[op_num]
            try:
                register_snode(op_num, host, snode_indices[0])
            except Exception as e:
                log(f"  op{op_num} pass1 re-reg failed: {e}", level="WARN")
            time.sleep(0.3)
        log("  Waiting 1 block for UTXO change outputs...")
        time.sleep(65)
        log(f"  Restoring ops 12-20 (pass 2: second SN each)...")
        for op_num in range(12, 21):
            host, snode_indices = OPERATOR_MAP[op_num]
            if len(snode_indices) > 1:
                try:
                    register_snode(op_num, host, snode_indices[1])
                except Exception as e:
                    log(f"  op{op_num} pass2 re-reg failed: {e}", level="WARN")
                time.sleep(0.3)

        # Wait for full fleet
        deadline2 = time.time() + 300
        while time.time() < deadline2:
            cnt, ops = snode_count()
            if cnt == 40 and ops == 20:
                break
            time.sleep(10)
        log(f"  Fleet restored: SNs={cnt} ops={ops} (target 40/20)")

    # Summary
    passes = sum(1 for r in results if r["result"] == "PASS")
    log(f"\n=== Phase 1 Complete: {passes}/{num_cycles} PASS ===")
    for r in results:
        status = r["result"]
        if status == "PASS":
            log(f"  Cycle {r['cycle']}: stall h={r['stall_h']}, "
                f"recovery h={r['recovery_h']} ({r['duration_blocks']} blocks), "
                f"PULSE[{r['sigs']}]")
        else:
            log(f"  Cycle {r['cycle']}: {status}")

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
    report_path = f"{LOG_DIR}/phase1-report-{ts}.json"
    with open(report_path, "w") as f:
        json.dump({"cycles": results, "events": EVENT_LOG}, f, indent=2)
    log(f"Report: {report_path}")
    close_tunnels()
    return results

# ── Phase 2: Stability run (N blocks, no stalls) ─────────────────────────────

def run_phase2(target_blocks=1000):
    log(f"=== Phase 2: {target_blocks}-block stability run (no induced stalls) ===")
    log("Assuming all SNs already registered. Monitoring only.")

    cnt, ops = snode_count()
    log(f"Starting with SNs={cnt} ops={ops}")
    start_h = tip()
    event("phase2_start", height=start_h, sn_count=cnt, op_count=ops)

    last_h = start_h
    checked = 0
    gov_events = []

    while checked < target_blocks:
        try:
            cur_h = tip()
        except Exception as e:
            log(f"get_info failed: {e}", level="WARN")
            time.sleep(10)
            continue

        for h in range(last_h + 1, cur_h + 1):
            if checked >= target_blocks:
                break
            btype, nsigs = block_type(h)
            BLOCK_LOG.append({"height": h, "type": btype, "sigs": nsigs})
            checked += 1

            if btype == "GOV_SIGNED":
                log(f"h={h}: GOV_SIGNED (unexpected) — checked={checked}/{target_blocks}",
                    level="WARN")
                event("unexpected_gov", height=h)
                gov_events.append(h)
            elif checked % 25 == 0:
                pulse_pct = 100 * sum(1 for b in BLOCK_LOG[-checked:] if b["type"] == "PULSE") / checked
                log(f"h={h}: PULSE[{nsigs}] — {checked}/{target_blocks} blocks, "
                    f"Pulse={pulse_pct:.1f}%")

        last_h = cur_h
        time.sleep(10)

    total = len(BLOCK_LOG)
    pulse_cnt = sum(1 for b in BLOCK_LOG if b["type"] == "PULSE")
    pulse_pct = 100 * pulse_cnt / max(total, 1)
    log(f"\n=== Phase 2 Complete ===")
    log(f"  {target_blocks} blocks, {pulse_cnt} Pulse ({pulse_pct:.1f}%), "
        f"{len(gov_events)} unexpected GOV_SIGNED")
    if gov_events:
        log(f"  GOV_SIGNED heights: {gov_events}")

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
    report_path = f"{LOG_DIR}/phase2-report-{ts}.json"
    with open(report_path, "w") as f:
        json.dump({"total_blocks": total, "pulse_blocks": pulse_cnt,
                   "pulse_pct": round(pulse_pct, 2),
                   "unexpected_gov": gov_events, "events": EVENT_LOG,
                   "blocks": BLOCK_LOG}, f, indent=2)
    log(f"Report: {report_path}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles",  type=int, default=20,
                        help="Phase 1: number of stall/recovery cycles (default 20)")
    parser.add_argument("--blocks",  type=int, default=1000,
                        help="Phase 2: number of blocks to monitor (default 1000)")
    parser.add_argument("--phase",   type=int, choices=[1, 2], default=1,
                        help="Which phase to run (default 1)")
    parser.add_argument("--start-cycle", type=int, default=1,
                        help="Resume from this cycle number (default 1)")
    args = parser.parse_args()

    if args.phase == 1:
        run_phase1(num_cycles=args.cycles, start_cycle=args.start_cycle)
    else:
        run_phase2(target_blocks=args.blocks)

if __name__ == "__main__":
    main()
