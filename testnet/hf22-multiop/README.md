# XEQM Private Testnet

Single-machine testnet: 1 seed + 12 service nodes, all on `127.0.0.1`, 5-second blocks.
Used to validate HF22 (`hf22_sn_policy`) changes before mainnet deployment.

## HF22 features under test

- **14-day forced deregistration lock** — `unlock_height = deregister_height + 20160` (20160 × 5s = 14 days)
- **Quorum deduplication** — 1 operator address per quorum slot
- **Lokinet opt-in** — `HAVE_LOKINET = true` in `mainnet.h`

## Prerequisites

Rebuild `xeqm-d` and `xeqm-rpc` from this repo before running the testnet:

```bash
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

## Critical source fixes required for HF22 testnet

### 1. Block reward serialization (`src/cryptonote_basic/cryptonote_basic.h`)

`b.reward` must be included in block serialization for `hf22_sn_policy`. Without this, peers
deserialize HF22 blocks with `b.reward = 0` (default), fail the `b.reward != 8.25 XEQM` check,
and the chain splits at HF22.

Find the block version guard that serializes `b.reward` for HF19/20/21 and add HF22:

```cpp
if (b.major_version == hf::hf19_reward_batching ||
    b.major_version == hf::hf20_governance_payouts_fix ||
    b.major_version == hf::hf21_weekly_batching ||
    b.major_version == hf::hf22_sn_policy) {
    // ... height/producer compat fields ...
    field(ar, "reward", b.reward);
}
```

### 2. Testnet governance wallet

At HF19+, the mining address receives nothing (`base_miner = 0`). Governance payments
(4.125 XEQM/block) go exclusively to `GOVERNANCE_WALLET_ADDRESS` in `testnet.h`. The
operator wallet must be this governance wallet to accumulate funds for SN registration.

Steps:
1. Start `xeqm-rpc --testnet --wallet-dir <dir> --rpc-bind-port 18185 --disable-rpc-login`
2. Create wallet: `POST /json_rpc {"method":"create_wallet","params":{"filename":"testnet-gov","password":"xeqm-testnet","language":"English"}}`
3. Get address: `{"method":"get_address"}`
4. Put that address in both slots of `GOVERNANCE_WALLET_ADDRESS` in `src/network_config/testnet.h`
5. Rebuild `xeqm-d`

## Testnet configuration (`src/network_config/testnet.h`)

```
TARGET_BLOCK_TIME        = 5s
BATCHING_INTERVAL_V2     = 5      (governance pays every 5 blocks)
SERVICE_NODE_PAYABLE_AFTER_BLOCKS = 4
PULSE_MIN_SERVICE_NODES  = 12
OXEN_STAKING_REQUIREMENT_TESTNET  = 100 XEQM (100 * COIN)
```

## Hardfork table (`src/cryptonote_basic/hardfork.cpp`, testnet section)

```cpp
hard_fork{hf::hf19_reward_batching, 0,  9,   1653632397},
hard_fork{hf::hf19_reward_batching, 1,  10,  1653632397},
hard_fork{hf::hf19_reward_batching, 2,  11,  1653632397},
hard_fork{hf::hf19_reward_batching, 3,  12,  1653632397},
hard_fork{hf::hf21_weekly_batching, 0,  14,  1653632397},
hard_fork{hf::hf22_sn_policy,       0,  350, 1653632397},
```

HF22 at block 350 gives ~294 blocks × 4.125 XEQM ≈ 1213 XEQM in the governance wallet
before HF22 fires, which is enough for 12 × 100 XEQM SN stakes.

## Port layout

| Role    | P2P   | Admin RPC | Quorumnet |
|---------|-------|-----------|-----------|
| seed    | 49000 | 49001     | —         |
| snode1  | 49100 | 49101     | 49102     |
| snode2  | 49200 | 49201     | 49202     |
| …       | …     | …         | …         |
| snode12 | 50200 | 50201     | 50202     |

## Running the testnet

```bash
# One command: launches all daemons, waits for 1200 XEQM, registers 12 SNs
python3 full-setup.py

# Monitor progress (separate terminal)
bash watch-testnet.sh
```

`full-setup.py` opens the `testnet-gov` wallet, starts the seed + 12 SNs, waits until
`unlocked_balance >= 1200 XEQM` (HF19+ needed, block ~295), then registers all 12 SNs
via `get_service_node_registration_cmd` + `register_service_node`.

## HF22 verification

After block 350, confirm in `get_info` that `hard_fork == 22`, then check:

1. **14-day lock**: Manually deregister an SN and verify `unlock_height = deregister_height + 20160`
2. **Quorum dedup**: Try registering a 13th SN with the same operator address and confirm
   quorum composition never includes the same address twice

## ETH mode guard

HF enum values in `src/cryptonote_config.h`:
```
hf22_sn_policy    = 22   ← our target
hf20_eth_transition = 23
hf21_eth            = 24  ← feature::ETH_BLS
hf22_eth_fixup      = 25
```

`feature::ETH_BLS = hf::hf21_eth = 24`. At HF22 (v=22), the guard `22 >= 24` is FALSE —
ETH-mode code is not activated.

## Troubleshooting

**`block reward for batching is incorrect: 0.000000000 != 8.250000000`**
→ Missing `hf22_sn_policy` in block serialization guard. Apply fix 1 above and rebuild.

**Wallet shows 0 XEQM after many blocks**
→ You are using the wrong wallet. At HF19+, only `GOVERNANCE_WALLET_ADDRESS` receives funds.
Open the `testnet-gov` wallet whose address matches `testnet.h`.

**SNs stuck at `active_sns = 0`**
→ SNs need 12 active peers for Pulse quorum. Check all 12 snode daemons are running
(`bash start-testnet.sh status`) and seed has synced (`curl -s http://127.0.0.1:49001/json_rpc ...`).

**pkill kills SSH tunnel**
→ Kill testnet processes by PID (`cat ~/xeqm-testnet/pids/*.pid | xargs kill`) rather than
`pkill -f xeqm-d`, which can hit the SSH reverse tunnel daemon.
