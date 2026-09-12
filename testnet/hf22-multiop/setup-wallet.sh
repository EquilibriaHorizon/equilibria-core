#!/bin/bash
# Create testnet wallet via wallet-rpc, mine premine, register all 12 SNs
set -euo pipefail

XEQMD=/home/svshearer/xeqm-core/build/bin/xeqm-d
WALLET_RPC=/home/svshearer/xeqm-core/build/bin/xeqm-rpc
WALLET_DIR=/home/svshearer/xeqm-testnet/wallet
WALLET_NAME=testnet-operator
WALLET_PASS=xeqm-testnet
WALLET_RPC_PORT=18183
SEED_RPC=49001

mkdir -p "$WALLET_DIR"

wrpc() {
    curl -sf http://127.0.0.1:$WALLET_RPC_PORT/json_rpc \
        -H 'Content-Type: application/json' \
        --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"$1\",\"params\":${2:-{}},\"id\":\"0\"}"
}

daemon_rpc() {
    local port=$1 method=$2
    curl -sf http://127.0.0.1:$port/json_rpc \
        -H 'Content-Type: application/json' \
        --data-binary "{\"jsonrpc\":\"2.0\",\"method\":\"$method\",\"params\":${3:-{}},\"id\":\"0\"}"
}

# --- Step 1: Start wallet-rpc (no wallet loaded initially) ---
WALLET_RPC_PID=/home/svshearer/xeqm-testnet/pids/wallet-rpc.pid
if [ -f "$WALLET_RPC_PID" ] && kill -0 "$(cat "$WALLET_RPC_PID")" 2>/dev/null; then
    echo "wallet-rpc already running"
else
    echo "=== Starting wallet-rpc daemon ==="
    "$WALLET_RPC" --testnet \
        --wallet-dir "$WALLET_DIR" \
        --rpc-bind-port $WALLET_RPC_PORT \
        --daemon-address 127.0.0.1:$SEED_RPC \
        --disable-rpc-login \
        --log-level 0 \
        >> /home/svshearer/xeqm-testnet/logs/wallet-rpc.log 2>&1 &
    echo $! > "$WALLET_RPC_PID"
    echo "  pid $! — polling until ready..."
    for _i in $(seq 1 30); do
        sleep 2
        _r=$(curl -sf http://127.0.0.1:$WALLET_RPC_PORT/json_rpc \
            -H 'Content-Type: application/json' \
            --data-binary '{"jsonrpc":"2.0","method":"get_version","params":{},"id":"0"}' 2>/dev/null)
        echo "$_r" | python3 -c 'import sys,json; json.load(sys.stdin)["result"]' >/dev/null 2>&1 && break
        echo "  still waiting ($_i)..."
    done
    echo "  wallet-rpc ready"
fi

# --- Step 2: Create wallet (or open existing) ---
if [ ! -f "$WALLET_DIR/$WALLET_NAME.keys" ]; then
    echo "=== Creating testnet wallet '$WALLET_NAME' ==="
    result=$(wrpc create_wallet \
        "{\"filename\":\"$WALLET_NAME\",\"password\":\"$WALLET_PASS\",\"language\":\"English\"}")
    echo "  $result"
else
    echo "=== Opening existing wallet '$WALLET_NAME' ==="
    result=$(wrpc open_wallet \
        "{\"filename\":\"$WALLET_NAME\",\"password\":\"$WALLET_PASS\"}")
    echo "  $result"
fi

# --- Step 3: Get wallet address ---
echo ""
echo "=== Getting wallet address ==="
addr_result=$(wrpc get_address '{"account_index":0}')
WALLET_ADDR=$(echo "$addr_result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d['result']['address'])
" 2>/dev/null)

if [ -z "$WALLET_ADDR" ]; then
    echo "ERROR: Could not get wallet address. wallet-rpc response:"
    echo "$addr_result"
    exit 1
fi
echo "  Address: $WALLET_ADDR"
echo "$WALLET_ADDR" > "$WALLET_DIR/address.txt"

# --- Step 4: Restart seed with mining to this wallet ---
echo ""
echo "=== Restarting seed with mining → $WALLET_ADDR ==="
SEED_PID=/home/svshearer/xeqm-testnet/pids/seed.pid
if [ -f "$SEED_PID" ] && kill -0 "$(cat "$SEED_PID")" 2>/dev/null; then
    kill "$(cat "$SEED_PID")" && sleep 3
fi
mkdir -p /home/svshearer/xeqm-testnet/data/seed
"$XEQMD" --testnet --non-interactive \
    --data-dir=/home/svshearer/xeqm-testnet/data/seed \
    --p2p-bind-ip=0.0.0.0 --p2p-bind-port=49000 \
    --rpc-admin=127.0.0.1:$SEED_RPC \
    --start-mining "$WALLET_ADDR" --mining-threads 2 \
    >> /home/svshearer/xeqm-testnet/logs/seed.log 2>&1 &
echo $! > "$SEED_PID"
echo "  Seed restarted (pid $!)"

# --- Step 5: Wait for premine (block 1) and wallet sync ---
echo ""
echo "=== Waiting for premine (block 1) to arrive in wallet ==="
for i in $(seq 1 60); do
    height=$(daemon_rpc $SEED_RPC get_height 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin)['result']['height'])" 2>/dev/null || echo 0)
    wrpc refresh '{}' >/dev/null 2>&1 || true
    balance=$(wrpc get_balance '{"account_index":0}' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin)['result']; print(d['balance'])" 2>/dev/null || echo 0)
    echo "  Block $height | Balance: $((balance / 1000000000)) XEQM"
    if [ "$balance" -gt 0 ] && [ "$height" -ge 5 ]; then
        echo "  Funds available!"
        break
    fi
    sleep 5
done

# --- Step 6: Register all 12 SNs ---
echo ""
echo "=== Registering 12 service nodes (10% fee, 100k XEQM each) ==="
STAKING_AMT=100000000000000  # 100,000 XEQM in atomic units

REGISTERED=0
for i in $(seq 1 12); do
    snode_rpc=$((49100 + (i-1)*100 + 1))
    echo -n "  snode$i (RPC :$snode_rpc) → "

    reg_data=$(daemon_rpc $snode_rpc get_service_node_registration_cmd \
        "{\"operator_cut\":\"10\",\"contributor_addresses\":[\"$WALLET_ADDR\"],\"contributor_amounts\":[$STAKING_AMT]}" \
        2>/dev/null) || { echo "FAILED (daemon not ready)"; continue; }

    reg_cmd=$(echo "$reg_data" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('result', {}).get('registration_cmd', ''))
" 2>/dev/null)

    if [ -z "$reg_cmd" ]; then
        echo "SKIP (empty cmd: check snode is synced)"
        continue
    fi

    result=$(wrpc relay_service_node_registration \
        "{\"registration_cmd\":\"$reg_cmd\"}" 2>/dev/null) || { echo "wallet-rpc call failed"; continue; }

    txid=$(echo "$result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('result', {}).get('txid', d.get('error', {}).get('message', 'error')))
" 2>/dev/null)
    echo "$txid"
    REGISTERED=$((REGISTERED+1))
    sleep 1
done

echo ""
echo "=== Done: $REGISTERED / 12 SNs registered ==="
echo ""
echo "Key milestones (at 5s/block):"
echo "  Block 240 = HF16 pulse starts    | ~$((240*5/60))min from genesis"
echo "  Block 249 = HF22 dedup + 14d lock| ~$((249*5/60))min from genesis"
echo ""
echo "Monitor: /home/svshearer/xeqm-testnet/watch-testnet.sh"
