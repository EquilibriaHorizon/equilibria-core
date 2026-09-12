#!/usr/bin/env python3
"""
Pre-mine distribution script.
Opens testnet-gov wallet, waits until enough XEQM is unlocked,
then sends to all 20 op wallets.

Run BEFORE launching orchestrator-multihost.py
"""
import json, urllib.request, time, sys
from datetime import datetime

WALLET_RPC = "http://127.0.0.1:18183/json_rpc"
SEED_RPC   = "http://127.0.0.1:49001/json_rpc"

# 100 XEQM per SN (100 * 10^9 atomic)
STAKING    = 100_000_000_000

# Stable ops (1-10): 2 SNs, register once = 200 XEQM, send 400 for buffer
# Stall ops (11-20): 2 SNs, 20 re-registers = 4000 XEQM needed, send 4500
STABLE_AMT = 400 * STAKING // 100   # 400 XEQM
STALL_AMT  = 4500 * STAKING // 100  # 4500 XEQM
TOTAL_NEEDED = 10 * STABLE_AMT + 10 * STALL_AMT

OP_ADDRESSES = {
    1:  "XEQTBSwU6RnTTZyuGA7LMkRAbAnr5GYbqUL3ZKnZfv9FfPgZqmrneoo8zDZKCGkwqvgrnZrUrsB6z3hv1B5vpcJa9b7yxesGWC",
    2:  "XEQTb7iPYRALiF4VDgnACZ8tn2wFYLT6vJtzRF69EA4HNbBaT6u7rfDJHyEb5mntkV9RnaAZqCLWuMqHHsqpDGrx51hfAt85Yg",
    3:  "XEQTJUouQ8GC3ywu83mDSrZmuet2W2BGagXoKzxnKg8AjYkruh5qXxpGBvqijYo82PfRJsPfEiY7MGpVT6SmcZwz6T9hviKoT8",
    4:  "XEQTZd6b2ZdjnZvyjiXqzQ3XtGzT85YbP8ZXXJXiLu2uUvUAfsofmsa7iyg1hyQnTBf4LGfR5Djw5VHzvED1MbAA7JDKS4c5MA",
    5:  "XEQTX5mSqqMgzvMUv7JJ1Y1tJN1tKNxLdiLZyps6uodTF4YLX593jty9tTVdcCsKgMWPUt4kp6p4HDnmFWiLGcQB75KhDrd6Ui",
    6:  "XEQTFDwQJVA6PrCWRyhQAGMQPRDFWVW27JF6LBKHDexZcronQzA37ao96Bw64JuZ4zXVich4iyJFgT6zgYNFGsig64MBhc8WQM",
    7:  "XEQTF5K4EpP3FSkKJzrS7EUs9ZnJJniLFfA6d1UqBhBFPEg4sZZnUEbCrNLh7k3buXXC56amxKhE7RK1LCSkFZ7S5fF947mJQv",
    8:  "XEQT7huFgmBXVNb1NRfDZePxGpjLr6CFZTm3PR7XzK6DHWqxFiedp9S4wzacGcg1KiiRhwMpvKxmZCU5z3ZwVU165mFv7rG6vK",
    9:  "XEQT9r6BLTX5Mum9eGqCj7iDvwJ1H1wyD66GmWDWBDeSZuMdEyGjzmVSZhV463KFq2HzKFeMyYzyv8MGQmkY9Qyx1hmHa5FaQw",
    10: "XEQTRDnNAP87F6Tkk39MyQRP3dJKPk1nj552sAHsPnhg9LnBtqpwopbARUufPnNea7b5ckbyiw5eNFQyCK2mabZRAHcSTVa4Qd",
    11: "XEQTZaRKbcHZEYyhSsN83tf32RPAbnXJHGLYcacXFSAXFQe7jM7138GdNr7dTX9JniNWpTMYSr4K1ZqX4WRYY5kx2p4YzPhBfH",
    12: "XEQTUyrCbmG3eWzBvCRB7NATDVVKWdAWZfnxZ1kiJ3JV4dqrLGHkeh763xcvRpLCuTaAjtWC9yUYgMzNT15DShNG2nLUj42ti9",
    13: "XEQTNxSR3haGLHeAB1S384BhxA8ukVSHKcuht4f1fJrgLP2ruLMPfZMRTjKCAcimqaWam3HUhVGkpETvjairBf9T8YY4CwhKnt",
    14: "XEQTDb23fQK7hQFCooCER71XDhsu7szYye88zkRT9aVXXSN5uL8wVPvcRe7Lz3wQdhAVDndEBotBSWzpm4iTQgfu3BL7e7w55L",
    15: "XEQTYJDN3MEZcjdJJ4amBAbcCkcWfNoCGgcUS5AJbcXVYFAxmuUiYcqDAXoHQTRRVZERukMX1JTLbBXbQBjNpiex6JtrwUes53",
    16: "XEQTCTV1aVUeLtLnRBoiaWX6xnpYtKkS1dGrefcSZycqWLikK1XoekE12wp66MNn7PiALsW4ZKKwPifq6NjhmtLn7bQB2sawSd",
    17: "XEQTMKRekjf7taayhfpkFJ2RuTk35TPjYNxb2MSjH9pyChJX9zzm5jRWojix2FWgQBZtPG7Kda3iMfhxU1qasSDw794JHMRbT7",
    18: "XEQTJYqPvBFPi3KwPsnQCzWE7ADJiZJNdQxNd4hvZpdd8iLskp2orksPpxpL32eswNfc4RDs5iLwiThF6YpxebTJ4KtowU2woS",
    19: "XEQTY6wnD3DWb8znp1zqGnja17yxdXhEJZR8F9UFTLNhG45BwNYhg4U34A43SVzym3A8uzvc3vd9yDWWfYJMMHjVAVVTfco4tX",
    20: "XEQT9F5pEmhiwo1BixNgrtivd3QbSyevp1MNahvYk9AkaLp8U6dVQJ9c5aENHmJxPvdekrR3fNM7CebAbvRvo9nh28Mboohwgk",
}

def ts():
    return datetime.utcnow().strftime("%H:%M:%S")

def rpc(url, method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "method": method,
                       "params": params or {}, "id": "0"}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def wallet(method, params=None):
    return rpc(WALLET_RPC, method, params)

def seed(method, params=None):
    return rpc(SEED_RPC, method, params)

def main():
    print(f"[{ts()}] Opening testnet-gov wallet...")
    r = wallet("open_wallet", {"filename": "testnet-gov", "password": "xeqm-testnet"})
    if "error" in r:
        print(f"ERROR opening wallet: {r['error']}")
        sys.exit(1)

    print(f"[{ts()}] Need {TOTAL_NEEDED/1e9:.0f} XEQM unlocked in governance wallet")
    print(f"         (stable ops: {STABLE_AMT/1e9:.0f} XEQM × 10 = {STABLE_AMT*10/1e9:.0f} XEQM)")
    print(f"         (stall ops:  {STALL_AMT/1e9:.0f} XEQM × 10 = {STALL_AMT*10/1e9:.0f} XEQM)")

    while True:
        try:
            wallet("refresh", {})
            bal = wallet("get_balance", {})["result"]
            total = bal["balance"]
            unlocked = bal["unlocked_balance"]
            chain_h = seed("get_info", {})["result"]["height"]
            print(f"[{ts()}] h={chain_h}  gov: {total/1e9:.1f} XEQM total, "
                  f"{unlocked/1e9:.1f} unlocked (need {TOTAL_NEEDED/1e9:.0f})")
            if unlocked >= TOTAL_NEEDED:
                print(f"[{ts()}] Sufficient unlocked balance! Proceeding with distribution.")
                break
        except Exception as e:
            print(f"[{ts()}] Waiting... ({e})")
        time.sleep(10)

    # Build transfer destinations
    destinations = []
    for op_num, addr in OP_ADDRESSES.items():
        amt = STALL_AMT if op_num >= 11 else STABLE_AMT
        destinations.append({"address": addr, "amount": amt})
        label = "stall" if op_num >= 11 else "stable"
        print(f"  op{op_num:2d} ({label}): {amt/1e9:.0f} XEQM → {addr[:20]}...")

    print(f"\n[{ts()}] Sending to all 20 op wallets via transfer_split...")
    try:
        result = wallet("transfer_split", {
            "destinations": destinations,
            "priority": 1,
            "get_tx_key": True,
        })
        if "error" in result:
            print(f"ERROR: {result['error']}")
            sys.exit(1)
        r = result["result"]
        hashes = r.get("tx_hash_list", [r.get("tx_hash", "?")])
        print(f"[{ts()}] SUCCESS — {len(hashes)} tx(s):")
        for h in hashes:
            print(f"  {h}")
    except Exception as e:
        print(f"ERROR sending: {e}")
        sys.exit(1)

    # Wait 70 blocks for confirmation
    print(f"\n[{ts()}] Waiting 70 blocks for confirmations...")
    chain_h = seed("get_info", {})["result"]["height"]
    target = chain_h + 70
    while True:
        try:
            h = seed("get_info", {})["result"]["height"]
            if h >= target:
                break
            print(f"[{ts()}] h={h}, waiting for h={target}...")
        except Exception:
            pass
        time.sleep(5)

    # Verify op wallet balances
    print(f"\n[{ts()}] Verifying op wallet balances...")
    all_ok = True
    for op_num in range(1, 21):
        needed = STALL_AMT if op_num >= 11 else STABLE_AMT
        wallet("open_wallet", {"filename": f"op{op_num}", "password": ""})
        time.sleep(0.5)
        wallet("refresh", {})
        bal = wallet("get_balance", {})["result"]
        u = bal["unlocked_balance"]
        ok = "✓" if u >= needed else "✗"
        print(f"  {ok} op{op_num:2d}: {u/1e9:.1f} XEQM unlocked (need {needed/1e9:.0f})")
        if u < needed:
            all_ok = False

    if all_ok:
        print(f"\n[{ts()}] All wallets funded. Ready for test.")
        print("Next step: restart seed with --fixed-difficulty=100000")
    else:
        print(f"\n[{ts()}] WARNING: some wallets underfunded!")

if __name__ == "__main__":
    main()
