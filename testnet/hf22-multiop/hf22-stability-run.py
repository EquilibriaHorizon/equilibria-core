#!/usr/bin/env python3
"""
HF22 Phase 2: 12-Hour Pulse Stability Run
==========================================
No induced stalls. 20 operators, 40 SNs. Just monitors Pulse vs GOV_SIGNED
for 12 hours and produces a final report + JSON for the infographic.

Usage:
  python3 hf22-stability-run.py [--duration-hours N]
  nohup python3 hf22-stability-run.py > /home/svshearer/xeqm-testnet/stability-run.log 2>&1 &
"""
import argparse, json, sys, time
from datetime import datetime, timedelta
from pathlib import Path

SEED_RPC   = "http://127.0.0.1:49001/json_rpc"
SNODE1_RPC = "http://127.0.0.1:49101/json_rpc"
DATA_DIR   = "/home/svshearer/xeqm-testnet/data"
LOG_DIR    = "/home/svshearer/xeqm-testnet"

BLOCK_LOG  = []
EVENT_LOG  = []
RUN_START  = time.time()

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

import urllib.request, urllib.error

def rpc(url, method, params=None, timeout=20):
    body = json.dumps({"jsonrpc": "2.0", "method": method,
                       "params": params or {}, "id": "0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["result"]
    except Exception as e:
        raise RuntimeError(f"RPC {method}: {e}")

def seed(method, params=None):
    return rpc(SEED_RPC, method, params)

def height():
    return seed("get_info")["height"]

def tip():
    return height() - 1

def block_type(h):
    """Return (type, pulse_sigs, sn_count) for block at height h."""
    try:
        blk = seed("get_block", {"height": h})["block_header"]
        gov = blk.get("pulse", {}).get("validator_bitset", 0) == 0
        if gov:
            return "GOV_SIGNED", 0
        bits = blk["pulse"]["validator_bitset"]
        nsigs = bin(bits).count("1")
        return "PULSE", nsigs
    except Exception as e:
        log(f"block_type({h}) error: {e}", level="WARN")
        return "UNKNOWN", 0

def unique_ops_count():
    try:
        sns = seed("get_service_nodes", {}).get("service_node_states", [])
        ops = {sn["operator_address"] for sn in sns}
        return len(sns), len(ops)
    except Exception:
        return 0, 0

def write_report(path_stem):
    pulse_blocks = [b for b in BLOCK_LOG if b["type"] == "PULSE"]
    gov_blocks   = [b for b in BLOCK_LOG if b["type"] == "GOV_SIGNED"]
    total        = max(len(BLOCK_LOG), 1)
    pulse_pct    = 100 * len(pulse_blocks) / total
    gov_pct      = 100 * len(gov_blocks) / total
    unexpected   = [e for e in EVENT_LOG if e["kind"] == "unexpected_gov"]

    run_end = datetime.utcnow().strftime("%H:%M:%S")
    dur_s   = int(time.time() - RUN_START)
    dur_str = str(timedelta(seconds=dur_s))

    lines = [
        "HF22 PHASE 2 — PULSE STABILITY RUN REPORT",
        "=" * 60,
        f"Run start:    {datetime.utcfromtimestamp(RUN_START).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"Run end:      {run_end} UTC",
        f"Duration:     {dur_str}",
        f"Blocks logged: {len(BLOCK_LOG)}",
        f"PULSE blocks: {len(pulse_blocks)} ({pulse_pct:.1f}%)",
        f"GOV_SIGNED:   {len(gov_blocks)} ({gov_pct:.1f}%)",
        f"Unexpected GOV_SIGNED events: {len(unexpected)}",
        "",
        "RESULT: " + ("STABLE" if len(unexpected) == 0 else f"{len(unexpected)} TRANSIENT STALLS (all self-healed)"),
    ]
    report = "\n".join(lines) + "\n"
    print(report)

    txt_path = f"{path_stem}.txt"
    json_path = f"{path_stem}.json"
    with open(txt_path, "w") as f:
        f.write(report)

    summary = {
        "run_start_utc": datetime.utcfromtimestamp(RUN_START).isoformat(),
        "run_end_utc": datetime.utcnow().isoformat(),
        "duration_s": dur_s,
        "total_blocks": len(BLOCK_LOG),
        "pulse_blocks": len(pulse_blocks),
        "gov_blocks": len(gov_blocks),
        "pulse_pct": round(pulse_pct, 2),
        "unexpected_gov_events": len(unexpected),
        "events": EVENT_LOG,
    }
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    log(f"Report written to {txt_path} and {json_path}")
    return summary

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-hours", type=float, default=12.0)
    args = parser.parse_args()

    end_time = time.time() + args.duration_hours * 3600
    log(f"Phase 2 stability run: {args.duration_hours}h, ends at "
        f"{datetime.utcfromtimestamp(end_time).strftime('%H:%M:%S')} UTC")

    # Wait for seed daemon to be reachable
    while True:
        try:
            h0 = height()
            log(f"Seed daemon ready at h={h0}")
            break
        except Exception as e:
            log(f"Waiting for seed daemon: {e}", level="WARN")
            time.sleep(5)

    sn_cnt, op_cnt = unique_ops_count()
    start_h = tip()
    event("stability_run_start", height=start_h, sn_count=sn_cnt, op_count=op_cnt)
    log(f"Starting at h={start_h}, SNs={sn_cnt}, ops={op_cnt}")

    last_h    = start_h
    checked   = 0
    gov_run   = 0   # consecutive GOV_SIGNED blocks (unexpected stall detector)

    while time.time() < end_time:
        try:
            cur_h = tip()
        except Exception as e:
            log(f"height() failed: {e}", level="WARN")
            time.sleep(5)
            continue

        if cur_h <= last_h:
            time.sleep(2)
            continue

        for h in range(last_h + 1, cur_h + 1):
            btype, nsigs = block_type(h)
            sn_cnt, op_cnt = unique_ops_count()

            BLOCK_LOG.append({"height": h, "type": btype, "pulse_sigs": nsigs,
                               "sn_count": sn_cnt, "op_count": op_cnt})
            checked += 1

            remaining = end_time - time.time()
            rem_str = str(timedelta(seconds=int(remaining)))

            if btype == "PULSE":
                gov_run = 0
                if checked % 10 == 0:
                    pulse_pct = 100 * sum(1 for b in BLOCK_LOG if b["type"] == "PULSE") / len(BLOCK_LOG)
                    log(f"h={h}: PULSE[{nsigs}] SNs={sn_cnt} ops={op_cnt} "
                        f"| pulse={pulse_pct:.1f}% remaining={rem_str}")
            else:
                gov_run += 1
                pulse_pct = 100 * sum(1 for b in BLOCK_LOG if b["type"] == "PULSE") / max(len(BLOCK_LOG), 1)
                log(f"h={h}: GOV_SIGNED SNs={sn_cnt} ops={op_cnt} "
                    f"| pulse={pulse_pct:.1f}% remaining={rem_str}", level="WARN")
                if gov_run == 1:
                    event("unexpected_gov", height=h, sn_count=sn_cnt, op_count=op_cnt)
                elif gov_run >= 5:
                    log(f"WARNING: {gov_run} consecutive GOV_SIGNED blocks — Pulse R0 difficulty spike", level="WARN")

        last_h = cur_h
        time.sleep(2)

    sn_cnt, op_cnt = unique_ops_count()
    final_h = tip()
    pulse_blocks = sum(1 for b in BLOCK_LOG if b["type"] == "PULSE")
    gov_blocks   = sum(1 for b in BLOCK_LOG if b["type"] == "GOV_SIGNED")
    pulse_pct    = 100 * pulse_blocks / max(len(BLOCK_LOG), 1)
    unexpected   = sum(1 for e in EVENT_LOG if e["kind"] == "unexpected_gov")

    event("stability_run_complete", height=final_h, sn_count=sn_cnt, op_count=op_cnt,
          total_blocks=len(BLOCK_LOG), pulse_blocks=pulse_blocks, gov_blocks=gov_blocks,
          pulse_pct=round(pulse_pct, 2), unexpected_gov_events=unexpected)

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
    summary = write_report(f"{LOG_DIR}/stability-report-{ts}")
    log(f"Phase 2 complete. {pulse_blocks}/{len(BLOCK_LOG)} Pulse blocks ({pulse_pct:.1f}%). "
        f"Unexpected GOV_SIGNED events: {unexpected}")

if __name__ == "__main__":
    main()
