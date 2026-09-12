# HF22 consensus fixes — implementation spec (Q5/Q6/Q7/Q11)

Branch: `feat/hf22-consensus-fixes` (cut from `feat/hf22-sn-policy`).
These are consensus-critical. Implement here, then **validate with the 20-operator harness**
(`testnet/hf22-multiop/hf22-12h-test.py` + `orchestrator-multihost.py`) and a **mixed old/new
binary** pass before merging into `release/hf22`.

## Design decisions (locked)
- **Option A only.** No open/anonymous miners — survival mode. Only an *authorized* key may
  produce fallback blocks. Do NOT add a permissionless PoW path.
- **Option C = short.** Mainnet `PULSE_MINER_FALLBACK_ROUNDS` already set to **2** (~60s) on
  `feat` (commit b7f3213). Rationale: on a Pulse stall the authorized miner resumes blocks fast so
  uptime proofs keep flowing and SNs (esp. new / low-credit operators) are not decommissioned.
- **This timing is consensus-critical** (`pulse.cpp:985` → `miner_fallback_timestamp` →
  `service_node_list.cpp:3224` quorum/validity). It is a compile-time `network_config` constant, not
  a runtime flag — changing it needs a coordinated fork. It is set as part of HF22.

## Q5 — fallback miner hardening
Current impl lives in `src/cryptonote_core/cryptonote_core.cpp`:
- `arg_fallback_miner_key` decl @ ~159, added @ ~375, loaded @ ~497-499 (`m_fallback_miner_key`).
- Signing in `handle_block_found` @ 2399; signs @ 2415-2421 with
  `b.signatures = {quorum_signature{0xFFFF, sig}}` (0xFFFF = fallback sentinel).
- Verify side references `sig.voter_index` @ `service_node_list.cpp:2788`.

**Q5a — fork-gate the verify + fallback-round logic on `hf22_sn_policy` (not `hf16_pulse`).**
Where the fallback signature is *accepted* and where `miner_fallback_timestamp` gates block type,
guard on `hf_version >= hf::hf22_sn_policy`. Reason: old/new binaries must not disagree on whether a
fallback block is valid during the upgrade window (>60s stall) → would split the chain. Mainnet scan
750→182928 shows zero miner blocks historically, so only the rollout window is at risk.

**Q5b — only sign fallback (non-Pulse) blocks.** `cryptonote_core.cpp:2415` — add `&& !b.has_pulse()`
to the signing condition so normal Pulse blocks are never fallback-signed.

**Q5c — dedicated fallback keypair (not the treasury spend key via argv).**
- Add a `FALLBACK_MINER_PUBKEY` (or per-nettype) constant to `network_config` so verifiers know the
  authorized pubkey without a CLI arg.
- Load the *secret* from a file path (arg is a path, not the hex key) so it isn't in the process list.
- Remove the unsynchronized static cache in `get_fallback_miner_pubkey`.
- Keep the gov key ONLY if a consensus rule truly requires the producer == gov address (it does not).

## Q6 — refill deduped obligations/checkpoint quorums (`service_node_list.cpp`)
HF22 dedup currently *drops* duplicate-operator seats without replacement, shrinking
obligations/checkpoint/blink quorums below target (per whitepaper they should be *replaced*).
Against mainnet (918 active / 202 operators / top-5 37.9%) this puts obligations quorums <7 validators
~4.6% and checkpoints <13 votes ~10.3% of the time. **Fix:** after operator-dedup, refill from the
remaining shuffled candidate list so sizes stay 10 / 20 / 10. (Pulse keeps 1-seat-per-operator.)

## Q7 — unify the Pulse candidate threshold on 12
`generate_pulse_quorum` bails at `< PULSE_QUORUM_NUM_VALIDATORS` (+1 for round>0) after leader removal;
the `update_from_block` round-0 path bails at 11. **Standardize both on 12** (defense.xeqmlabs.com: at
11, a block leader holding one SN can drop round-0 to 10 signatures — below the 7-sig safety floor).
Add a shared constant/assert so the two paths cannot drift again.

## Q11 — move the hardcoded 14-day deregistration lock to `network_config`
`service_node_list.cpp:1337-1339`:
```cpp
auto lock_dur = (hf_version >= hf::hf22_sn_policy)
                      ? std::chrono::hours(14 * 24)          // <-- hardcoded
                      : netconf.DEREGISTRATION_LOCK_DURATION;
```
- Add `const std::chrono::seconds DEREGISTRATION_LOCK_DURATION_V2;` to `network_config`
  (`network_config.h` ~140, next to `DEREGISTRATION_LOCK_DURATION`).
- Set it in **every** nettype initializer (designated-init leaves unset fields = 0s):
  mainnet = `14 * 24h` (preserve behavior), testnet/devnet/stagenet short, fakechain/localdev tiny.
- Replace the hardcoded `std::chrono::hours(14 * 24)` with `netconf.DEREGISTRATION_LOCK_DURATION_V2`.
Behavior-preserving on mainnet; lets testnet iterate.

## Validation gate (before merge to release)
1. Build all platforms on CI (macOS Intel on `macmini-intel`).
2. Run `testnet/hf22-multiop/` 20-operator stall/recovery cycles → confirm dedup + fallback + refill.
3. Mixed old/new binary pass to confirm the Q5a fork-gate prevents a split.
