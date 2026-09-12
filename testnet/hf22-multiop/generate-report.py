#!/usr/bin/env python3
"""
Post-run report generator for HF22 12-hour test.
Reads the JSON event/block log produced by hf22-12h-test.py and
outputs a detailed human-readable report + ASCII timeline.

Usage:
  python3 generate-report.py report-20260725-1400.json
"""
import json, sys, math
from datetime import datetime

def load(path):
    with open(path) as f:
        return json.load(f)

def block_type_char(btype):
    if btype == "PULSE":   return "P"
    if btype == "GOV_SIGNED": return "G"
    return "?"

def ascii_timeline(blocks, width=80):
    if not blocks: return ""
    min_h = blocks[0]["h"]
    max_h = blocks[-1]["h"]
    span = max_h - min_h + 1
    cells = width
    btype_map = {b["h"]: b["type"] for b in blocks}
    result = []
    for i in range(cells):
        h = min_h + int(i * span / cells)
        btype = btype_map.get(h, "?")
        result.append("█" if btype == "PULSE" else "░" if btype == "GOV_SIGNED" else "?")
    return "".join(result)

def main():
    if len(sys.argv) < 2:
        print("Usage: generate-report.py <report.json>")
        sys.exit(1)

    data = load(sys.argv[1])
    events = data.get("events", [])
    blocks = data.get("blocks", [])
    summary = data.get("summary", {})

    pulse_blocks = [b for b in blocks if b["type"] == "PULSE"]
    gov_blocks   = [b for b in blocks if b["type"] == "GOV_SIGNED"]
    total = len(blocks)

    stall_events   = [e for e in events if e["kind"] == "stall_confirmed"]
    r1_events      = [e for e in events if e["kind"] == "recovery1_confirmed"]
    r1_failed      = [e for e in events if e["kind"] == "recovery1_failed"]
    r2_events      = [e for e in events if e["kind"] == "recovery2_complete"]
    unexpected     = [e for e in events if e["kind"] == "unexpected_stall"]

    setup_e = next((e for e in events if e["kind"] == "setup_complete"), None)
    hf22_e  = next((e for e in events if e["kind"] == "hf22_fired"), None)
    done_e  = next((e for e in events if e["kind"] in ("test_complete","test_interrupted","test_aborted")), None)

    print("=" * 70)
    print("HF22 PULSE STALL/RECOVERY — TEST REPORT")
    print("=" * 70)
    if setup_e:
        print(f"Setup complete at h={setup_e['height']}: {setup_e['sn_count']} SNs, {setup_e['op_count']} ops")
    if hf22_e:
        print(f"HF22 fired at h=250 | Pre-HF22 Pulse blocks: {hf22_e.get('pulse_pre_hf22','?')}")
    if done_e:
        print(f"Test status: {done_e['kind']} | Elapsed: {done_e['elapsed_s']//3600}h {(done_e['elapsed_s']%3600)//60}m")
    print()

    print("BLOCK STATISTICS")
    print("-" * 40)
    print(f"Total blocks logged : {total}")
    print(f"PULSE blocks        : {len(pulse_blocks)} ({100*len(pulse_blocks)/max(total,1):.1f}%)")
    print(f"GOV_SIGNED blocks   : {len(gov_blocks)} ({100*len(gov_blocks)/max(total,1):.1f}%)")
    if pulse_blocks:
        sigs = [b["sigs"] for b in pulse_blocks]
        print(f"Pulse sig count avg : {sum(sigs)/len(sigs):.1f} (min={min(sigs)}, max={max(sigs)})")
    print()

    print("STALL / RECOVERY CYCLE TABLE")
    print("-" * 70)
    print(f"{'Cy':>3} {'Stall h':>7} {'Ops':>4} {'Resume h':>8} {'Blks':>5} {'Sigs':>5} {'Result':>8}")
    print("-" * 70)
    for i, se in enumerate(stall_events):
        cyc = se.get("cycle", i+1)
        re_list = [r for r in r1_events if r.get("cycle") == cyc]
        rf_list = [r for r in r1_failed if r.get("cycle") == cyc]
        if re_list:
            re = re_list[0]
            dur = re.get("stall_duration_blocks", "?")
            sigs = re.get("pulse_sigs", "?")
            print(f"{cyc:>3} {se['height']:>7} {se['unique_ops']:>4} {re['height']:>8} {str(dur):>5} {str(sigs):>5} {'✓ PASS':>8}")
        elif rf_list:
            print(f"{cyc:>3} {se['height']:>7} {se['unique_ops']:>4} {'—':>8} {'—':>5} {'—':>5} {'✗ FAIL':>8}")
        else:
            print(f"{cyc:>3} {se['height']:>7} {se['unique_ops']:>4} {'—':>8} {'—':>5} {'—':>5} {'pending':>8}")
    print("-" * 70)
    print(f"Cycles: {len(stall_events)} | Recoveries: {len(r1_events)} | Failures: {len(r1_failed)}")
    if unexpected:
        print(f"Unexpected stalls: {len(unexpected)} (heights: {[e['height'] for e in unexpected]})")
    print()

    # Stall duration statistics
    durations = [e.get("stall_duration_blocks") for e in r1_events if e.get("stall_duration_blocks") is not None]
    if durations:
        print("STALL DURATION STATISTICS (blocks from stall→recovery)")
        print(f"  Min: {min(durations)} blocks")
        print(f"  Max: {max(durations)} blocks")
        print(f"  Avg: {sum(durations)/len(durations):.1f} blocks")
        print()

    # ASCII timeline
    if blocks:
        print("ASCII TIMELINE (█=PULSE, ░=GOV_SIGNED)")
        print("[" + ascii_timeline(blocks, width=68) + "]")
        h_min = blocks[0]["h"]
        h_max = blocks[-1]["h"]
        print(f" h={h_min}{'':>55}h={h_max}")
        print()

    # Stall markers on timeline
    if stall_events and r1_events and blocks:
        print("STALL/RECOVERY EVENTS (height markers):")
        for i, (se, re) in enumerate(zip(stall_events, r1_events)):
            print(f"  Cycle {se.get('cycle',i+1)}: stall h={se['height']} → resume h={re['height']} ({re.get('stall_duration_blocks','?')} blks)")
    print()
    print("=" * 70)
    print("END OF REPORT")

if __name__ == "__main__":
    main()
