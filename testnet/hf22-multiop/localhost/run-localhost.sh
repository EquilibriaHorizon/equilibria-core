#!/bin/bash
# Turnkey SINGLE-HOST HF22 testnet: seed + 40 SNs (20 operators x 2) all on 127.0.0.1.
# No SSH, no access to any production fleet. Parameterized version of the proven
# restart-clean-40.sh used for the defense.xeqmlabs.com run.
#
# Usage:
#   XEQMD=/path/to/xeqm-d ./run-localhost.sh
#   (defaults to ../../../build/bin/xeqm-d relative to this script)
#
# Fallback miner:
#   Default = SINGLE miner on the seed using the governance spend key, because the CURRENT
#   verify path (get_fallback_miner_pubkey) authorizes only the gov wallet pubkey.
#   TWO-MINER mode (TWO_MINER=1) starts a second dedicated-key miner — but it only VALIDATES
#   once Q5c lands (FALLBACK_MINER_PUBKEYS as a set + verify-against-any). See README-localhost.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
XEQMD="${XEQMD:-$HERE/../../../build/bin/xeqm-d}"
WORK="${WORK:-$HOME/xeqm-hf22-localhost}"
BASE_DIR="$WORK/data"; LOG_DIR="$WORK/logs"
SEED_P2P=49000; SEED_RPC=49001
NUM_SNODES="${NUM_SNODES:-40}"

# testnet-only governance keys (NOT mainnet). Also the current single-miner fallback key.
GOV_WALLET=XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx
FALLBACK_KEY=0c999a88be252215b48735272e5cf3dd86d54f850bb0bc8bfe9aea0de7549405
TWO_MINER="${TWO_MINER:-0}"                       # set 1 after Q5c to start a 2nd dedicated miner
FALLBACK_KEY_2="${FALLBACK_KEY_2:-}"              # dedicated secret key for miner 2 (post-Q5c)

[ -x "$XEQMD" ] || { echo "xeqm-d not found/executable at: $XEQMD (set XEQMD=...)"; exit 1; }
mkdir -p "$LOG_DIR"
start() { local name=$1; shift; "$XEQMD" "$@" > "$LOG_DIR/$name.log" 2>&1 & echo "  $name pid=$!"; }

echo "=== xeqm-d: $XEQMD ; work dir: $WORK ; SNs: $NUM_SNODES ==="
echo "=== Stopping any existing localhost testnet ==="
pkill -f "testnet.*data-dir=$BASE_DIR" 2>/dev/null || true
sleep 2

echo "=== Starting seed (fallback miner #1) ==="
start seed \
    --testnet --non-interactive \
    --data-dir="$BASE_DIR/seed" \
    --p2p-bind-ip=0.0.0.0 --p2p-bind-port=$SEED_P2P \
    --rpc-admin=127.0.0.1:$SEED_RPC \
    --dev-allow-local-ips --in-peers 80 \
    --start-mining "$GOV_WALLET" --mining-threads 2 \
    --fallback-miner-key "$FALLBACK_KEY"
sleep 3

if [ "$TWO_MINER" = "1" ]; then
  [ -n "$FALLBACK_KEY_2" ] || { echo "TWO_MINER=1 requires FALLBACK_KEY_2 (dedicated secret key)"; exit 1; }
  echo "=== Starting fallback miner #2 (dedicated key) — validates only after Q5c ==="
  start miner2 \
    --testnet --non-interactive \
    --data-dir="$BASE_DIR/miner2" \
    --p2p-bind-ip=0.0.0.0 --p2p-bind-port=49010 \
    --rpc-admin=127.0.0.1:49011 \
    --dev-allow-local-ips \
    --seed-node=127.0.0.1:$SEED_P2P --add-priority-node=127.0.0.1:$SEED_P2P \
    --start-mining "$GOV_WALLET" --mining-threads 2 \
    --fallback-miner-key "$FALLBACK_KEY_2"
  sleep 2
fi

echo "=== Starting snodes 1-$NUM_SNODES ==="
for i in $(seq 1 "$NUM_SNODES"); do
    p2p=$((49000 + i * 100)); rpc=$((p2p + 1)); qnet=$((p2p + 2))
    start "snode$i" \
        --testnet --non-interactive \
        --data-dir="$BASE_DIR/snode$i" \
        --service-node --dev-allow-local-ips \
        --p2p-bind-ip=0.0.0.0 --p2p-bind-port=$p2p \
        --rpc-admin=127.0.0.1:$rpc --quorumnet-port=$qnet \
        --service-node-public-ip=127.0.0.1 \
        --seed-node=127.0.0.1:$SEED_P2P --add-priority-node=127.0.0.1:$SEED_P2P \
        --log-level=pulse:info
done
echo "=== Up. Next: python3 ../full-setup.py (fund+register), then ../hf22-12h-test.py (stall/recovery). ==="
echo "=== Seed RPC 127.0.0.1:$SEED_RPC ; logs in $LOG_DIR ==="
