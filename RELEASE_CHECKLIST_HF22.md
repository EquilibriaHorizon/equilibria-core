# HF22 Release Checklist / Runbook

Single source of truth for cutting the HF22 release. Items marked ✅ are already done on the
branches; ⏳ is for Dom.

## Branch topology
- `fix/hf22-combined` — CI/infra + stability PRs (deployed on the 54-node fleet as v1.0.7-dcd35c18a).
- `feat/hf22-sn-policy` — HF22 consensus (operator dedup, GOV_SIGNED fallback miner, enum, fork height).
- `feat/hf22-consensus-fixes` — review branch: Q5b + Q11 (build-verified) + spec (`IMPLEMENTATION_NOTES_HF22.md`)
  for Q5a/Q5c/Q6/Q7.

## Merge order
1. Cut `release/hf22` from `main`.
2. Merge `fix/hf22-combined` (carries: macOS Intel self-hosted routing + Boost_NO_SYSTEM_PATHS,
   #53 ncurses/readline fix, macOS signing pipeline, fork-PR approval).
3. Merge `feat/hf22-sn-policy` (carries: consensus + Q1 .gitmodules + Q3 lokinet=false + Q2 sentinels +
   Q11-via-review + Q8 harness + Option C fallback=2 + Q12 height=220000 + aider cleanup).
4. Merge/apply `feat/hf22-consensus-fixes` (Q5b, Q11) and implement the remaining consensus items below.

## Status of Dom's questions
- Q1 submodule ✅ (fork at XEQMLabs/oxen-mq; .gitmodules repointed)
- Q2 sentinels ✅ (23/24/25 pinned on feat, build-verified; merge keeps feat's values over PR #45's 22/23)
- Q3 HAVE_LOKINET=false ✅
- Q4 ship GOV_SIGNED fallback ✅ (decision; document in whitepaper/release notes)
- Q5a fork-gate ⏳ Dom — gate fallback sign+verify on hf22_sn_policy (both sides, in lockstep). See spec.
- Q5b skip Pulse blocks ✅ (build-verified on review branch)
- Q5c dedicated keypair(s) ⏳ Dom — now a SET for the multi-miner design (below). See spec.
- Q6 quorum refill ⏳ Dom — refill deduped obligations/checkpoint to 10/20/10. See spec.
- Q7 unify pulse threshold on 12 ⏳ Dom — three spots interact (generate_pulse_quorum's
  PULSE_QUORUM_NUM_VALIDATORS(+1), the dedup fallback's PULSE_MIN_SERVICE_NODES=12, and the
  update_from_block round-0 bail at 11). Make them consistent; needs a careful eye. See spec.
- Q8 20-op harness ✅ committed (testnet/hf22-multiop/) — ⏳ Dom RUN it + a mixed old/new-binary pass.
- Q9 testnet revert ⏳ Dom — testnet.h intermixes the private-testnet rewrite (NETWORK_ID, seeds,
  prefixes, gov wallet, staking req) with NEW HF22 network_config fields (PULSE_MINER_FALLBACK_ROUNDS,
  DEREGISTRATION_LOCK_DURATION_V2). Revert ONLY the private-testnet values to main; KEEP the new fields
  and keep hf22_sn_policy at a testnet height. (Left to Dom to void dropping HF22 fields / breaking compile.)
- Q11 14-day lock → DEREGISTRATION_LOCK_DURATION_V2 ✅ (build-verified; mainnet preserves 14d)
- Q12 fork height ✅ placeholder 220000 — ⏳ SET the final height/timestamp from the binary-publish date
  (>=3 weeks after binaries are public; ~1440 blocks/day at 60s).
- Q13 operator fee ✅ already 10% (cryptonote_config.h MAX_OPERATOR_FEE_BASIS = 1000) — no change.

## Test harness — location + how to run
Full rig: `testnet/hf22-multiop/` — the 20-operator / 40-SN Pulse dedup + fallback harness behind
defense.xeqmlabs.com. Key files: `hf22-12h-test.py` (stall/recovery cycles), `full-setup.py`
(fund + register), `orchestrator-multihost.py` (optional multi-host driver), `generate-report.py`.

Turnkey SINGLE-HOST run (one box, no fleet, no SSH): `testnet/hf22-multiop/localhost/`
```bash
export XEQMD=/path/to/xeqm-core/build/bin/xeqm-d      # feat binary (private-testnet params)
cd testnet/hf22-multiop/localhost && bash run-localhost.sh   # seed + 40 SNs on 127.0.0.1
python3 ../full-setup.py                               # fund + register 20 operators (2 SNs each)
python3 ../hf22-12h-test.py --cycles 20               # stall/recovery cycles
```
Details in `testnet/hf22-multiop/localhost/README-localhost.md`. Two-miner failover: `TWO_MINER=1`
(after Q5c). Needs a binary built from the private-testnet config (before the Q9 revert).

## macOS signing (✅ pipeline wired; ⏳ secrets)
Both macOS jobs: build → dylibbundler → codesign (Developer ID Application, hardened runtime) →
signed .pkg (Developer ID Installer) → notarize (App Store Connect API key) → staple → upload.
No-op until secrets present. Add these 9 as **repo OR org-scoped-to-xeqm-core** Actions secrets:
MACOS_CERT_APP_P12_BASE64, MACOS_CERT_INSTALLER_P12_BASE64, MACOS_CERT_PASSWORD, MACOS_SIGN_APP_IDENTITY,
MACOS_SIGN_INSTALLER_IDENTITY, MACOS_KEYCHAIN_PASSWORD, MACOS_NOTARY_KEY_P8_BASE64, MACOS_NOTARY_KEY_ID,
MACOS_NOTARY_ISSUER_ID.

## Fallback miner deployment (survival mode, no single point of failure)
- Run >=2 authorized fallback miners on different providers: **maple (OVH)** + **OCI (Oracle)** [both
  live seeds] and/or **missoula (Contabo)**. Each holds its OWN dedicated key (from a file, per Q5c);
  all pubkeys go in FALLBACK_MINER_PUBKEYS. Optional local primary/secondary start-delay (no fork needed).
- Fallback engages after PULSE_MINER_FALLBACK_ROUNDS=2 (~60s) so uptime proofs keep flowing.

### Responsibility split (Dom needs NO access to maple/OCI)
- **Dom (dom + validation):** implements the FALLBACK_MINER_PUBKEYS mechanism (Q5c) and validates the
  2-miner failover ENTIRELY on his own localhost box — `TWO_MINER=1` runs miner#1 (seed) + miner#2
  (dedicated key) both on 127.0.0.1; kill #1 mid-stall to prove #2 keeps producing. Uses LOCAL test keys.
- **Ops (has maple/OCI access):** at release, generate the real per-server dedicated keypairs, place each
  secret on maple + OCI, and fill the MAINNET FALLBACK_MINER_PUBKEYS with those two pubkeys. Not Dom's job.

## Pre-tag gate (do NOT tag until all true)
- [ ] Submodule resolves from XEQMLabs/oxen-mq (CI `submodules: recursive` green).
- [ ] Q5a/Q5c/Q6/Q7 implemented + reviewed.
- [ ] 20-operator harness pass + mixed old/new-binary pass (Q8).
- [ ] Fork height set from publish date; >=2 fallback miners keyed + running.
- [ ] macOS secrets present → signed/notarized/stapled .pkg on both arches.
- [ ] Full CI green on release/hf22 (all 6 targets).
