# HF22 validation on ONE machine — no fleet, no SSH

This runs the entire 20-operator / 40-SN private testnet on a single box. It does **not** touch any
production service node — it's an isolated `--testnet` network on `127.0.0.1` with `--dev-allow-local-ips`.

## Run it
```bash
# 1. Build the HF22 binary (feat/hf22-sn-policy — keeps the private-testnet params the harness needs)
#    then point the harness at it:
export XEQMD=/path/to/xeqm-core/build/bin/xeqm-d

# 2. Bring up seed + 40 SNs locally
./run-localhost.sh

# 3. Fund + register the 20 operators (2 SNs each), then run stall/recovery cycles
python3 ../full-setup.py
python3 ../hf22-12h-test.py --cycles 20
```
Everything lives under `~/xeqm-hf22-localhost/` (override with `WORK=`). Reset by deleting that dir.

## What it validates today (single fallback miner)
- HF22 operator dedup forms/'skips' Pulse by unique-operator count.
- Stall when operators drop below threshold → **authorized fallback miner (the seed) keeps producing** →
  Pulse resumes automatically when operators return. This is the defense.xeqmlabs.com result, reproducible
  on one machine.

## Two-miner failover (dedicated keys) — needs Q5c first
The current verify path (`get_fallback_miner_pubkey`) authorizes **only the governance pubkey**, so the
harness uses the gov key for the single miner. After **Q5c** lands (`FALLBACK_MINER_PUBKEYS` as a set +
verify-against-any), enable a second dedicated-key miner:
```bash
# generate a dedicated testnet keypair (do NOT reuse the gov key)
$XEQMD-wallet --testnet --generate-new-wallet /tmp/fbk2 --mnemonic-language English --command spendkey
# put its PUBKEY in the testnet FALLBACK_MINER_PUBKEYS set, then:
TWO_MINER=1 FALLBACK_KEY_2=<dedicated-secret> ./run-localhost.sh
```
Kill the seed mid-stall to confirm miner #2 keeps the chain alive (no single point of failure).

## Notes
- Needs a binary built from the private-testnet config, i.e. **before the Q9 public-testnet revert**
  (or a private-testnet build profile).
- ~40 daemons on one host is fine (a Mac mini ran 38); ensure enough RAM/FDs.
