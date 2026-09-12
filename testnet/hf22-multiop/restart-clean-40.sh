#!/bin/bash
# 40-SN testnet restart for 12-hour HF22 stall/recovery test
# SNs 1-40: 20 unique operators (2 SNs each), 127.0.0.1, dev-allow-local-ips
# Seed: dev-allow-local-ips, Option-A fallback miner
set -euo pipefail

XEQMD=/home/svshearer/xeqm-core/build/bin/xeqm-d
BASE_DIR=/home/svshearer/xeqm-testnet/data
LOG_DIR=/home/svshearer/xeqm-testnet/logs
SEED_P2P=49000
SEED_RPC=49001

GOV_WALLET=XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx
FALLBACK_KEY=0c999a88be252215b48735272e5cf3dd86d54f850bb0bc8bfe9aea0de7549405

mkdir -p "$LOG_DIR"

start() {
    local name=$1; shift
    "$XEQMD" "$@" > "$LOG_DIR/$name.log" 2>&1 &
    echo "  $name pid=$!"
}

echo "=== Stopping any existing testnet processes ==="
pkill -f "testnet.*data-dir=$BASE_DIR" 2>/dev/null || true
sleep 2

echo "=== Starting seed ==="
start seed \
    --testnet --non-interactive \
    --data-dir="$BASE_DIR/seed" \
    --p2p-bind-ip=0.0.0.0 --p2p-bind-port=$SEED_P2P \
    --rpc-admin=127.0.0.1:$SEED_RPC \
    --dev-allow-local-ips \
    --in-peers 80 \
    --start-mining "$GOV_WALLET" \
    --mining-threads 2 \
    --fallback-miner-key "$FALLBACK_KEY"

sleep 3

echo "=== Starting snodes 1-40 ==="
for i in $(seq 1 40); do
    p2p=$((49000 + i * 100))
    rpc=$((p2p + 1))
    qnet=$((p2p + 2))
    start "snode$i" \
        --testnet --non-interactive \
        --data-dir="$BASE_DIR/snode$i" \
        --service-node \
        --dev-allow-local-ips \
        --p2p-bind-ip=0.0.0.0 --p2p-bind-port=$p2p \
        --rpc-admin=127.0.0.1:$rpc \
        --quorumnet-port=$qnet \
        --service-node-public-ip=127.0.0.1 \
        --seed-node=127.0.0.1:$SEED_P2P \
        --add-priority-node=127.0.0.1:$SEED_P2P \
        --log-level=pulse:info
done

echo ""
echo "Waiting 15s for seed sync..."
sleep 15
HEIGHT=$(curl -s http://127.0.0.1:$SEED_RPC/json_rpc \
    -d '{"jsonrpc":"2.0","method":"get_info","id":"0"}' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["height"]-1)' 2>/dev/null || echo "?")
echo "Seed at h=$HEIGHT"
echo "All 41 processes started (1 seed + 40 snodes)"
