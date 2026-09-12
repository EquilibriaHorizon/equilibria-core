#!/bin/bash
# Test Option A + Option C: Kill all SNs, wait for fallback round timeout (~150s),
# verify seed produces governance-signed fallback miner blocks (voter_index=65535).
# Requires: full-setup.py completed, all 20 SNs registered and running.
set -euo pipefail

SEED_RPC="http://127.0.0.1:49001/json_rpc"
PID_DIR=/home/svshearer/xeqm-testnet/pids
# Option C: testnet fallback rounds = 1 × 30s = 30s before miner block is accepted
FALLBACK_WAIT=50    # 30s + 20s margin
NUM_SNODES=20

jrpc() { curl -s "$1" -d "{\"jsonrpc\":\"2.0\",\"id\":\"0\",\"method\":\"$2\",\"params\":{$3}}"; }

echo "=== Option A Fallback Test ==="
echo "This test kills all $NUM_SNODES service nodes to simulate catastrophic quorum failure,"
echo "waits for the Pulse round timeout (PULSE_MINER_FALLBACK_ROUNDS × 30s, Option C),"
echo "then verifies the seed produces governance-signed fallback blocks."
echo ""

# Current state
INFO=$(jrpc "$SEED_RPC" "get_info" "")
HEIGHT=$(echo "$INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['height'])")
HF=$(echo "$INFO"     | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['hard_fork'])")
echo "Pre-test: height=$HEIGHT  hf=$HF"

if [ "$HF" -lt 22 ]; then
    echo "ERROR: HF22 not yet active (hf=$HF). Wait for block 600 first."
    exit 1
fi

SN_LIST=$(jrpc "$SEED_RPC" "get_service_nodes" "\"include_json\":false")
SN_COUNT=$(echo "$SN_LIST" | python3 -c "import sys,json; d=json.load(sys.stdin)['result']; print(len(d.get('service_node_states', d.get('service_nodes_infos',[]))))")
echo "Active SNs before kill: $SN_COUNT"
if [ "$SN_COUNT" -lt 1 ]; then
    echo "ERROR: no SNs found. Run full-setup.py first."
    exit 1
fi

# Kill all SN daemons (not the seed — seed does the fallback mining)
echo ""
echo "Killing all $NUM_SNODES SN daemons..."
for i in $(seq 1 $NUM_SNODES); do
    pf="$PID_DIR/snode$i.pid"
    if [ -f "$pf" ]; then
        pid=$(cat "$pf")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo -n "$i "
        fi
    fi
done
echo ""
echo "All SNs killed. Chain will stall after current Pulse round."
echo ""

PRE_HEIGHT=$HEIGHT

# Wait for Option C timeout + margin, then check for new blocks
echo "Waiting ${FALLBACK_WAIT}s for fallback block (Option C: 1×30s round on testnet)..."
sleep "$FALLBACK_WAIT"

INFO2=$(jrpc "$SEED_RPC" "get_info" "")
HEIGHT2=$(echo "$INFO2" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['height'])")
echo "Post-wait: height=$HEIGHT2"

if [ "$HEIGHT2" -le "$PRE_HEIGHT" ]; then
    echo ""
    echo "FAIL: Chain did not advance after ${FALLBACK_WAIT}s. Check seed log:"
    tail -20 /home/svshearer/xeqm-testnet/logs/seed.log
    exit 1
fi

echo "Chain advanced $((HEIGHT2-PRE_HEIGHT)) blocks. Checking for Option A signatures..."
echo ""

# Inspect blocks produced after SNs were killed
FOUND_FALLBACK=0
for h in $(seq "$PRE_HEIGHT" "$HEIGHT2"); do
    BLOCK=$(jrpc "$SEED_RPC" "get_block" "\"height\":$h")
    SIG_INFO=$(echo "$BLOCK" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)['result']
    b=json.loads(d['json'])
    sigs=b.get('signatures',[])
    pulse_sigs=[s for s in sigs if s['voter_index'] != 65535]
    gov_sigs=[s for s in sigs if s['voter_index'] == 65535]
    if gov_sigs:
        print('OPTION_A_FALLBACK voter_index=65535 sig='+gov_sigs[0]['signature'][:16]+'...')
    elif pulse_sigs:
        print('PULSE sigs='+str(len(pulse_sigs)))
    else:
        print('MINER_UNSIGNED')
except Exception as e:
    print('ERR:'+str(e))
" 2>/dev/null || echo "parse_error")
    echo "  h=$h: $SIG_INFO"
    if echo "$SIG_INFO" | grep -q "OPTION_A_FALLBACK"; then
        FOUND_FALLBACK=1
    fi
done

echo ""
if [ "$FOUND_FALLBACK" -eq 1 ]; then
    echo "PASS: Option A fallback blocks confirmed — governance signature (voter_index=65535) present."
    echo "PASS: Option C confirmed — fallback fired after ~${FALLBACK_WAIT}s (PULSE_MINER_FALLBACK_ROUNDS × 30s)."
else
    echo "FAIL: No Option A governance-signed fallback blocks found in h=${PRE_HEIGHT}..${HEIGHT2}."
    echo "      Check: is --fallback-miner-key set on seed? HF22 active?"
fi

echo ""
echo "=== Test complete ==="
