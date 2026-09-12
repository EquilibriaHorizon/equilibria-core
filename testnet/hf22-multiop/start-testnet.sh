#!/bin/bash
# Missoula testnet SNs — ops 11-15, 2 SNs each = snodes 1-10
# Public IP: 144.126.159.227
# Ports: p2p=49100+N*100, rpc=49101+N*100 (loopback), qnet=49102+N*100
# Connects to seed: 134.56.143.2:49000

set -e
BINARY=~/xeqm-testnet/xeqm-d
DATADIR=~/xeqm-testnet/data
SEED=134.56.143.2:49000
PUBIP=144.126.159.227
LOGDIR=~/xeqm-testnet/logs

mkdir -p "$LOGDIR"

for i in $(seq 1 10); do
  IDX=$((i - 1))
  P2P=$((49100 + IDX * 100))
  RPC=$((49101 + IDX * 100))
  QNET=$((49102 + IDX * 100))
  DATAPATH="$DATADIR/snode$i"
  mkdir -p "$DATAPATH"

  "$BINARY" \
    --testnet \
    --non-interactive \
    --data-dir="$DATAPATH" \
    --service-node \
    --dev-allow-local-ips \
    --p2p-bind-ip=0.0.0.0 \
    --p2p-bind-port="$P2P" \
    --rpc-admin=127.0.0.1:"$RPC" \
    --quorumnet-port="$QNET" \
    --service-node-public-ip="$PUBIP" \
    --seed-node="$SEED" \
    --add-priority-node="$SEED" \
    --log-level=pulse:info \
    > "$LOGDIR/snode$i.log" 2>&1 &

  echo "Started missoula snode$i PID=$! p2p=$P2P qnet=$QNET"
done

echo "All 10 missoula SNs started"
