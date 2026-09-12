#!/bin/bash
# Live monitor: shows each new block as PULSE / MINER_FALLBACK / GOV_SIGNED.
# Runs until killed. Prints a summary line at every block transition.
#
# PULSE      = Pulse quorum produced this block (voter_index 0-10 signatures)
# MINER_FALL = Miner fallback before HF22 (no signatures)
# GOV_SIGNED = Option A: governance-signed miner fallback post-HF22 (voter_index 65535)

SEED_RPC="http://127.0.0.1:49001/json_rpc"
HF22_BLOCK=400
LAST_H=0
PULSE_COUNT=0
MINER_COUNT=0
GOV_COUNT=0

jrpc() { curl -s "$1" -d "{\"jsonrpc\":\"2.0\",\"id\":\"0\",\"method\":\"$2\",\"params\":{$3}}" 2>/dev/null; }

echo "=== Pulse Monitor (HF22 at block $HF22_BLOCK) ==="
echo "  Block types: PULSE=quorum-produced  MINER_FALL=pre-HF22-fallback  GOV_SIGNED=Option-A-post-HF22"
echo "  Watching chain..."
echo ""

while true; do
    INFO=$(jrpc "$SEED_RPC" "get_info" "")
    H=$(echo "$INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['height'])" 2>/dev/null)
    HF=$(echo "$INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['hard_fork'])" 2>/dev/null)

    if [ -z "$H" ] || [ "$H" = "None" ]; then
        sleep 2; continue
    fi

    if [ "$H" -gt "$LAST_H" ]; then
        for bh in $(seq $((LAST_H + 1)) "$H"); do
            BLOCK=$(jrpc "$SEED_RPC" "get_block" "\"height\":$bh")
            TYPE=$(echo "$BLOCK" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)['result']
    b = json.loads(d['json'])
    sigs = b.get('signatures', [])
    gov  = [s for s in sigs if s['voter_index'] == 65535]
    qrm  = [s for s in sigs if s['voter_index'] != 65535]
    if qrm:
        print('PULSE[' + str(len(qrm)) + ']')
    elif gov:
        print('GOV_SIGNED')
    else:
        print('MINER_FALL')
except Exception as e:
    print('ERR:' + str(e))
" 2>/dev/null || echo "ERR")

            # Tally
            case "$TYPE" in
                PULSE*) PULSE_COUNT=$((PULSE_COUNT+1)) ;;
                GOV*)   GOV_COUNT=$((GOV_COUNT+1)) ;;
                *)      MINER_COUNT=$((MINER_COUNT+1)) ;;
            esac

            # Flag HF22 boundary
            NOTE=""
            if [ "$bh" -eq "$HF22_BLOCK" ]; then
                NOTE="  <<<< HF22 ACTIVATES HERE >>>>"
            fi

            printf "  h=%-5d hf=%-3d  %-15s  [Pulse:%-4d Miner:%-4d GovSign:%-4d]%s\n" \
                "$bh" "$HF" "$TYPE" "$PULSE_COUNT" "$MINER_COUNT" "$GOV_COUNT" "$NOTE"
        done
        LAST_H=$H
    fi
    sleep 3
done
