#!/bin/bash
# Monitor private testnet: chain height, HF version, active SNs, quorum formation
SEED_RPC=49001

rpc() { curl -sf http://127.0.0.1:$1/json_rpc -H 'Content-Type: application/json' \
    --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"$2\",\"params\":${3:-{}},\"id\":1}"; }

watch -n 3 '
SEED_RPC=49001

info=$(curl -sf http://127.0.0.1:'$SEED_RPC'/json_rpc -H "Content-Type: application/json" \
    --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"get_info\",\"params\":{},\"id\":1}" 2>/dev/null)

height=$(echo "$info" | python3 -c "import sys,json; d=json.load(sys.stdin)[\"result\"]; print(d[\"height\"])" 2>/dev/null || echo "?")
version=$(echo "$info" | python3 -c "import sys,json; d=json.load(sys.stdin)[\"result\"]; print(d.get(\"version\",\"?\"))" 2>/dev/null || echo "?")

hf_info=$(curl -sf http://127.0.0.1:'$SEED_RPC'/json_rpc -H "Content-Type: application/json" \
    --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"hard_fork_info\",\"params\":{},\"id\":1}" 2>/dev/null)
hf=$(echo "$hf_info" | python3 -c "import sys,json; d=json.load(sys.stdin)[\"result\"]; print(d[\"version\"])" 2>/dev/null || echo "?")

sns=$(curl -sf http://127.0.0.1:'$SEED_RPC'/json_rpc -H "Content-Type: application/json" \
    --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"get_service_nodes\",\"params\":{},\"id\":1}" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin)[\"result\"]; print(len(d[\"service_node_states\"]))" 2>/dev/null || echo "?")

active_sns=$(curl -sf http://127.0.0.1:'$SEED_RPC'/json_rpc -H "Content-Type: application/json" \
    --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"get_service_nodes\",\"params\":{\"active_only\":true},\"id\":1}" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin)[\"result\"]; print(len(d[\"service_node_states\"]))" 2>/dev/null || echo "?")

echo "=== XEQM Private Testnet === $(date -u +%H:%M:%S UTC)"
echo ""
echo "  Chain height : $height"
echo "  HF version   : $hf  (HF16/pulse=240  HF22/dedup=350)"
echo "  Daemon vers  : $version"
echo "  SNs total    : $sns"
echo "  SNs active   : $active_sns  (need 12 for pulse quorum)"
echo ""
if [ "$height" != "?" ] && [ "$height" -lt 240 ] 2>/dev/null; then
    blocks_to_hf16=$((240 - height))
    echo "  → HF16 (pulse) in ~$blocks_to_hf16 blocks (~$((blocks_to_hf16*5))s)"
elif [ "$height" != "?" ] && [ "$height" -lt 350 ] 2>/dev/null; then
    blocks_to_hf22=$((350 - height))
    echo "  → HF22 (dedup) in ~$blocks_to_hf22 blocks (~$((blocks_to_hf22*5))s)"
elif [ "$height" != "?" ] && [ "$height" -ge 350 ] 2>/dev/null; then
    echo "  *** HF22 ACTIVE — quorum dedup + 14-day lock enforced ***"
fi
echo ""
echo "SN status per node (RPC port → active/inactive):"
for i in $(seq 1 12); do
    port=$((49101 + (i-1)*100))
    sn_info=$(curl -sf http://127.0.0.1:$port/json_rpc -H "Content-Type: application/json" \
        --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"get_service_node_status\",\"params\":{},\"id\":1}" 2>/dev/null)
    active=$(echo "$sn_info" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    sn=d[\"result\"][\"service_node_state\"]
    status = \"active\" if sn.get(\"active\") else \"inactive\"
    proofs = sn.get(\"last_uptime_proof\",0)
    print(f\"{status} (proof:{proofs})\")
except:
    print(\"offline\")
" 2>/dev/null || echo "offline")
    printf "  snode%-2d :$port → %s\n" $i "$active"
done
'
