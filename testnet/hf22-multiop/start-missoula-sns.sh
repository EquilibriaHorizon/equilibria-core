#!/bin/bash
BINARY=/home/svshearer/xeqm-testnet/xeqm-d
DATADIR=/home/svshearer/xeqm-testnet/data
SEED=134.56.143.2:49000
PUBIP=144.126.159.227
LOGDIR=/home/svshearer/xeqm-testnet/logs
mkdir -p "$LOGDIR"
for i in $(seq 1 10); do
  IDX=$((i - 1))
  P2P=$((49100 + IDX * 100))
  RPC=$((49101 + IDX * 100))
  QNET=$((49102 + IDX * 100))
  DATAPATH="$DATADIR/snode$i"
  mkdir -p "$DATAPATH"
  nohup "$BINARY" --testnet --non-interactive \
    --data-dir="$DATAPATH" --service-node --dev-allow-local-ips \
    --p2p-bind-ip=0.0.0.0 --p2p-bind-port="$P2P" \
    --rpc-admin=127.0.0.1:"$RPC" --quorumnet-port="$QNET" \
    --service-node-public-ip="$PUBIP" \
    --seed-node="$SEED" --add-priority-node="$SEED" \
    --fixed-difficulty=60000 \
    --log-level=pulse:info \
    > "$LOGDIR/snode$i.log" 2>&1 &
  echo "missoula snode$i PID=$! p2p=$P2P"
done
echo "Done"
