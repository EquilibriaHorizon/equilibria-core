#!/bin/bash
# Kill all testnet daemons + wallet-rpc, wipe chain data + wallet files for a clean restart.
# The wallet must be wiped along with the chain: the wallet's ring DB (keyed by key image)
# persists between runs. On a fresh chain, governance TX pubkeys differ, producing different
# key images. Stale ring DB entries that accidentally match new key images cause
# "Known ring does not include the spent output" during SN registration.
# full-setup.py restores the wallet fresh from the fixed governance spend+view keys.
set -euo pipefail

BASE_DIR=/home/svshearer/xeqm-testnet
PID_DIR=$BASE_DIR/pids
DATA_DIR=$BASE_DIR/data
LOG_DIR=$BASE_DIR/logs
WALLET_DIR=$BASE_DIR/wallet

echo "=== Testnet reset ==="

echo "Stopping all daemons..."
for pidfile in "$PID_DIR"/*.pid; do
    [ -f "$pidfile" ] || continue
    pid=$(cat "$pidfile")
    name=$(basename "$pidfile" .pid)
    if kill -0 "$pid" 2>/dev/null; then
        echo "  killing $name (pid $pid)"
        kill "$pid"
    fi
    rm -f "$pidfile"
done

echo "Waiting for processes to exit..."
sleep 4

echo "Wiping chain data..."
rm -rf "$DATA_DIR"

echo "Wiping wallet (stale ring DB causes ring errors on next run)..."
rm -f "$WALLET_DIR/testnet-gov" \
      "$WALLET_DIR/testnet-gov.keys" \
      "$WALLET_DIR/testnet-gov.address.txt" \
      "$WALLET_DIR/address.txt"

echo "Wiping logs..."
rm -f "$LOG_DIR"/*.log

echo ""
echo "Reset complete. Run ./full-setup.py to start fresh testnet."
