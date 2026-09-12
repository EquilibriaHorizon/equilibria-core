#!/usr/bin/env python3
"""Register 12 testnet SNs via JSON-RPC."""
import json, urllib.request, time, sys

WALLET_RPC = "http://127.0.0.1:18183/json_rpc"
WALLET_ADDR = "XEQTC6kizY24NhBgRtzpFLMSs5XiSytDu6FSYuzuX4TgTNbp5QtHaSmEszVFT48ZqtNVBRroPVvCFZ88EGmenEPV3647DYan8y"
STAKING_AMT = 100_000_000_000  # 100 XEQM

def rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": "0"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

# Refresh wallet first
try:
    rpc(WALLET_RPC, "refresh", {})
except Exception as e:
    print(f"wallet refresh error: {e}")

# Get balance
try:
    bal = rpc(WALLET_RPC, "get_balance", {"account_index": 0})["result"]
    unlocked = bal["unlocked_balance"] // 1_000_000_000
    print(f"Wallet unlocked: {unlocked} XEQM  (need {12 * STAKING_AMT // 1_000_000_000} XEQM)")
except Exception as e:
    print(f"balance check failed: {e}")
    sys.exit(1)

print(f"=== Registering 12 SNs (100 XEQM each, 10% fee) ===")
registered = 0

for i in range(1, 13):
    snode_rpc = f"http://127.0.0.1:{49100 + (i-1)*100 + 1}/json_rpc"
    print(f"  snode{i:02d} -> ", end="", flush=True)

    # Get registration command from snode daemon
    try:
        resp = rpc(snode_rpc, "get_service_node_registration_cmd", {
            "operator_cut": "10",
            "contributor_addresses": [WALLET_ADDR],
            "contributor_amounts": [STAKING_AMT],
            "staking_requirement": STAKING_AMT,
        })
    except Exception as e:
        print(f"daemon unreachable: {e}")
        continue

    if "error" in resp:
        print(f"ERROR: {resp['error']['message']}")
        continue

    reg_cmd = resp.get("result", {}).get("registration_cmd", "")
    if not reg_cmd:
        print("empty registration_cmd")
        continue

    # Submit via wallet-rpc
    try:
        relay = rpc(WALLET_RPC, "register_service_node",
                    {"register_service_node_str": reg_cmd})
    except Exception as e:
        print(f"relay failed: {e}")
        continue

    if "error" in relay:
        print(f"RELAY ERROR: {relay['error']['message']}")
        continue

    txid = relay.get("result", {}).get("tx_hash", "no-txid")
    print(txid)
    registered += 1
    time.sleep(1)

print(f"\nRegistered: {registered} / 12")
print("Monitor: watch -n3 bash /home/svshearer/xeqm-testnet/watch-testnet.sh")
