#!/bin/bash
WALLET_RPC_PORT=18183
WALLET_ADDR=XEQTC6kizY24NhBgRtzpFLMSs5XiSytDu6FSYuzuX4TgTNbp5QtHaSmEszVFT48ZqtNVBRroPVvCFZ88EGmenEPV3647DYan8y
STAKING_AMT=100000000000  # 100 XEQM

echo '=== Registering 12 service nodes (100 XEQM each) ==='
REGISTERED=0

for i in $(seq 1 12); do
    snode_rpc=$((49100 + (i-1)*100 + 1))
    printf '  snode%-2d (RPC:%d) -> ' "$i" "$snode_rpc"

    reg_data=$(curl -sf "http://127.0.0.1:${snode_rpc}/json_rpc" \
        -H 'Content-Type: application/json' \
        --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"get_service_node_registration_cmd\",\"params\":{\"operator_cut\":\"10\",\"contributor_addresses\":[\"$WALLET_ADDR\"],\"contributor_amounts\":[$STAKING_AMT],\"staking_requirement\":$STAKING_AMT},\"id\":\"0\"}" 2>/dev/null)

    reg_cmd=$(echo "$reg_data" | python3 -c \
        'import sys,json; print(json.load(sys.stdin).get("result",{}).get("registration_cmd",""))' 2>/dev/null)

    if [ -z "$reg_cmd" ]; then
        echo "SKIP - daemon not ready"
        continue
    fi

    reg_cmd_j=$(python3 -c 'import sys,json; print(json.dumps(sys.argv[1]))' "$reg_cmd")

    result=$(curl -sf "http://127.0.0.1:${WALLET_RPC_PORT}/json_rpc" \
        -H 'Content-Type: application/json' \
        --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"relay_service_node_registration\",\"params\":{\"registration_cmd\":${reg_cmd_j}},\"id\":\"0\"}" 2>/dev/null)

    txid=$(echo "$result" | python3 -c \
        'import sys,json; d=json.load(sys.stdin); print(d.get("result",{}).get("txid", d.get("error",{}).get("message","parse-error")))' 2>/dev/null)
    echo "$txid"
    REGISTERED=$((REGISTERED+1))
    sleep 1
done

echo ""
echo "Registered: $REGISTERED / 12"
echo "HF22 fires at block 249 -- quorum dedup + 14-day lock active"
