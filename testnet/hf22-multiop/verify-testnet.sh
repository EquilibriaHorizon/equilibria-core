#!/bin/bash
# Verify HF22 testnet state: SN count, height, HF, Option A block signature, unlock lock.
# Run after full-setup.py completes successfully.
set -euo pipefail

SEED_RPC="http://127.0.0.1:49001/json_rpc"
NUM_SNODES=20
HF22_BLOCK=400

jrpc() { curl -s "$1" -d "{\"jsonrpc\":\"2.0\",\"id\":\"0\",\"method\":\"$2\",\"params\":{$3}}"; }

echo "=== HF22 Testnet Verification ==="
echo ""

# Chain state
INFO=$(jrpc "$SEED_RPC" "get_info" "")
HEIGHT=$(echo "$INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['height'])")
HF=$(echo "$INFO"     | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['hard_fork'])")
echo "Chain: height=$HEIGHT  hard_fork=$HF"
echo ""

# SN registration count
SN_LIST=$(jrpc "$SEED_RPC" "get_service_nodes" "\"include_json\":false")
SN_COUNT=$(echo "$SN_LIST" | python3 -c "import sys,json; d=json.load(sys.stdin)['result']; print(len(d.get('service_node_states', d.get('service_nodes_infos',[]))))")
echo "Service nodes registered: $SN_COUNT / $NUM_SNODES"
if [ "$SN_COUNT" -eq "$NUM_SNODES" ]; then
    echo "  PASS: all $NUM_SNODES SNs registered"
else
    echo "  FAIL: expected $NUM_SNODES, got $SN_COUNT"
fi
echo ""

# HF22 check
if [ "$HEIGHT" -lt "$HF22_BLOCK" ]; then
    echo "HF22: not yet (fires at block $HF22_BLOCK, currently h=$HEIGHT)"
elif [ "$HF" -ge 22 ]; then
    echo "HF22: ACTIVE (hf=$HF at h=$HEIGHT)"
else
    echo "HF22: FAIL — h>=$HF22_BLOCK but hf=$HF"
fi
echo ""

# Option A: check a recent block for governance auth signature (voter_index=0xFFFF=65535)
echo "Option A signature check (last 5 blocks)..."
for h in $(python3 -c "print(' '.join(str(max(0,$HEIGHT-5+i)) for i in range(5)))"); do
    BLOCK=$(jrpc "$SEED_RPC" "get_block" "\"height\":$h")
    SIGS=$(echo "$BLOCK" | python3 -c "
import sys,json
d=json.load(sys.stdin)['result']
b=json.loads(d['json'])
sigs=b.get('signatures',[])
print(len(sigs),sigs[0]['voter_index'] if sigs else 'none')
" 2>/dev/null || echo "parse_error")
    echo "  h=$h: sigs=$SIGS"
done
echo ""

# Pulse check: all 20 SNs should produce Pulse blocks at this height (post-registration)
if [ "$SN_COUNT" -ge "$NUM_SNODES" ] && [ "$HEIGHT" -gt "$((HF22_BLOCK + 20))" ]; then
    echo "Checking for Pulse activity (SN quorum blocks)..."
    RECENT=$(jrpc "$SEED_RPC" "get_block" "\"height\":$((HEIGHT-1))")
    IS_PULSE=$(echo "$RECENT" | python3 -c "
import sys,json
d=json.load(sys.stdin)['result']
b=json.loads(d['json'])
sigs=[s for s in b.get('signatures',[]) if s['voter_index'] != 65535]
print('PULSE' if sigs else 'MINER')
" 2>/dev/null || echo "unknown")
    echo "  Block h=$((HEIGHT-1)): $IS_PULSE"
    echo ""
fi

echo "=== Done ==="
