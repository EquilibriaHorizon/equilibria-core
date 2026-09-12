#!/bin/bash
# Wipe all testnet state and start fresh 40-SN testnet
set -euo pipefail

BASE_DIR=/home/svshearer/xeqm-testnet/data
LOG_DIR=/home/svshearer/xeqm-testnet/logs
WALLET_DIR=/home/svshearer/xeqm-testnet/wallet

echo "=== Stopping all testnet processes ==="
pkill -f "xeqm-d.*testnet" 2>/dev/null && echo "killed xeqm-d" || echo "none running"
pkill -f "xeqm-rpc.*18183" 2>/dev/null && echo "killed wallet-rpc" || echo "wallet-rpc not running"
sleep 3

echo "=== Wiping chain data (keeping scripts) ==="
rm -rf "$BASE_DIR"/seed "$BASE_DIR"/snode* 2>/dev/null || true
mkdir -p "$BASE_DIR"

echo "=== Wiping wallet data ==="
# Remove ALL wallet data — cache files have no extension in this wallet-rpc version
rm -rf "$WALLET_DIR" && mkdir -p "$WALLET_DIR"

echo "=== Wiping logs ==="
rm -f "$LOG_DIR"/*.log 2>/dev/null || true
mkdir -p "$LOG_DIR"

echo "=== Starting fresh testnet (40 SNs) ==="
bash /home/svshearer/xeqm-testnet/restart-clean-40.sh

echo ""
echo "Done. Run the 12-hour test with:"
echo "  python3 /home/svshearer/xeqm-testnet/hf22-12h-test.py --duration-hours 12"
echo "  (or add 2>&1 | tee /home/svshearer/xeqm-testnet/logs/12h-test.log)"
