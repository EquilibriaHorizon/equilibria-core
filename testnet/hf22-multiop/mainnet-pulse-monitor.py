#!/usr/bin/env python3
"""
Mainnet Pulse monitor — checks PULSE vs GOV_SIGNED block ratio on mainnet.
Used to compare R0 timeout frequency between mainnet and HF22 testnet.

Usage:
  python3 mainnet-pulse-monitor.py [--lookback N] [--duration-mins N]

  --lookback N    : scan last N historical blocks before live monitoring (default 200)
  --duration-mins : run live monitoring for this many minutes (default 120)
"""
import argparse, json, sys, time
from datetime import datetime, timedelta
import urllib.request

RPC_URL   = "http://127.0.0.1:18231/json_rpc"
RUN_START = time.time()

def rpc(method, params=None, timeout=20):
    body = json.dumps({"jsonrpc":"2.0","method":method,
                       "params":params or {},"id":"0"}).encode()
    req = urllib.request.Request(RPC_URL, data=body,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["result"]

def now(): return datetime.utcnow().strftime("%H:%M:%S")
def elapsed(): return str(timedelta(seconds=int(time.time()-RUN_START)))
def log(msg, level="INFO"): print(f"[{now()} +{elapsed()}] {level}: {msg}", flush=True)

def block_info(h):
    """Return (type, pulse_sigs) for block at height h."""
    try:
        blk = rpc("get_block", {"height": h})["block_header"]
        pulse = blk.get("pulse", {})
        vbits = pulse.get("validator_bitset", 0)
        if vbits == 0:
            return "GOV_SIGNED", 0
        return "PULSE", bin(vbits).count("1")
    except Exception as e:
        log(f"block_info({h}) error: {e}", level="WARN")
        return "UNKNOWN", 0

def print_summary(blocks, label):
    total = len(blocks)
    if total == 0:
        log(f"{label}: no blocks")
        return
    pulse = sum(1 for b in blocks if b[1] == "PULSE")
    gov   = sum(1 for b in blocks if b[1] == "GOV_SIGNED")
    pulse_pct = 100 * pulse / total
    log(f"{'='*60}")
    log(f"{label}")
    log(f"  Total blocks : {total}")
    log(f"  PULSE        : {pulse} ({pulse_pct:.2f}%)")
    log(f"  GOV_SIGNED   : {gov} ({100*gov/total:.2f}%)")
    if gov > 0:
        gov_heights = [h for h,t,_ in blocks if t == "GOV_SIGNED"]
        log(f"  GOV heights  : {gov_heights}")
    log(f"{'='*60}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, default=200,
                        help="Historical blocks to scan before live monitoring")
    parser.add_argument("--duration-mins", type=float, default=120,
                        help="Minutes to run live monitoring after historical scan")
    args = parser.parse_args()

    info = rpc("get_info")
    cur_h = info["height"] - 1
    log(f"Mainnet RPC at h={cur_h} (target={info['target']}s, version={info.get('version','?')})")

    # ── Historical scan ───────────────────────────────────────────────────────
    scan_start = cur_h - args.lookback + 1
    log(f"Scanning last {args.lookback} blocks: h={scan_start}→{cur_h}")

    hist = []
    gov_runs = []
    for h in range(scan_start, cur_h + 1):
        btype, nsigs = block_info(h)
        hist.append((h, btype, nsigs))
        if btype == "GOV_SIGNED":
            log(f"  GOV_SIGNED at h={h}", level="WARN")
        elif h % 50 == 0:
            done = h - scan_start + 1
            pct = 100 * sum(1 for _,t,_ in hist if t == "PULSE") / len(hist)
            log(f"  h={h} scanned ({done}/{args.lookback}) running Pulse={pct:.1f}%")
        time.sleep(0.05)   # gentle — don't hammer the RPC

    print_summary(hist, f"HISTORICAL: last {args.lookback} mainnet blocks")

    # ── Live monitoring ───────────────────────────────────────────────────────
    end_time = time.time() + args.duration_mins * 60
    log(f"Live monitoring for {args.duration_mins:.0f} min (ends {datetime.utcfromtimestamp(end_time).strftime('%H:%M UTC')})")

    live = []
    last_h = cur_h
    checked = 0

    while time.time() < end_time:
        try:
            new_h = rpc("get_info")["height"] - 1
        except Exception as e:
            log(f"get_info failed: {e}", level="WARN")
            time.sleep(10)
            continue

        for h in range(last_h + 1, new_h + 1):
            btype, nsigs = block_info(h)
            live.append((h, btype, nsigs))
            checked += 1

            if btype == "GOV_SIGNED":
                log(f"GOV_SIGNED at h={h} — R0 timeout on mainnet!", level="WARN")
            elif checked % 20 == 0:
                total_live = len(live)
                pulse_live = sum(1 for _,t,_ in live if t == "PULSE")
                pct = 100 * pulse_live / max(total_live, 1)
                remaining = timedelta(seconds=int(end_time - time.time()))
                log(f"h={h}: PULSE[{nsigs}] — {total_live} blocks live, {pct:.1f}% Pulse, remaining {remaining}")

        last_h = new_h
        time.sleep(10)

    all_blocks = hist + live
    print_summary(live, f"LIVE: {len(live)} mainnet blocks over {args.duration_mins:.0f} min")
    print_summary(all_blocks, f"COMBINED: {len(all_blocks)} mainnet blocks total")

    # Final verdict
    total_gov = sum(1 for _,t,_ in all_blocks if t == "GOV_SIGNED")
    if total_gov == 0:
        log("VERDICT: Zero GOV_SIGNED blocks on mainnet. R0 timeouts are a testnet-only artifact.")
        log("LIKELY CAUSE: Testnet PoW difficulty is near-zero (CPU miner, 5s blocks, fresh chain).")
        log("  When Pulse R0 fails even briefly, the miner fills the slot in milliseconds.")
        log("  On mainnet (60s target, CPU PoW calibrated to 60s), the miner can't win before Pulse retries.")
    else:
        log(f"VERDICT: {total_gov} GOV_SIGNED blocks found on mainnet — R0 timeouts occur in production too.")
        gov_heights = [h for h,t,_ in all_blocks if t == "GOV_SIGNED"]
        log(f"  Heights: {gov_heights}")

if __name__ == "__main__":
    main()
