# HF22 consensus fixes — implementation spec (Q5/Q6/Q7/Q11)

Branch: `feat/hf22-consensus-fixes` (cut from `feat/hf22-sn-policy`).
These are consensus-critical. Implement here, then **validate with the 20-operator harness**
(`testnet/hf22-multiop/hf22-12h-test.py` + `orchestrator-multihost.py`) and a **mixed old/new
binary** pass before merging into `release/hf22`.

## Design decisions (locked)
- **Option A only, but MULTIPLE authorized miners (no single point of failure).** No open/anonymous
  miners — survival mode. Fallback blocks must be signed by one of a *set* of authorized keys held on
  independent servers on different providers, so if one operator/provider is down another can keep the
  chain alive. Do NOT add a permissionless PoW path.
  - Chosen servers: **maple (OVH)** + **OCI (Oracle)** [both are live seeds] and/or **missoula (Contabo)**.
    Pick >=2 on different providers. All are currently reachable; none retired.
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

**Q5c — dedicated fallback keypair(S) — now a SET, for redundancy (not the treasury spend key via argv).**
- Add `FALLBACK_MINER_PUBKEYS` (a **list/set** of authorized pubkeys) to `network_config`. Verify accepts a
  fallback block signed by **any** key in the set. This is the consensus change that enables >=2 miners.
- Each miner server holds its **own** dedicated secret (one per server: maple, OCI, missoula), loaded from a
  **file** (arg is a path, not hex) so no key is in the process list and a single key leak != treasury and !=
  the other miners. Generate distinct keypairs per server; put all their pubkeys in `FALLBACK_MINER_PUBKEYS`.
- Remove the unsynchronized static cache in `get_fallback_miner_pubkey`.
- **Collision handling (LOCAL, not consensus — tunable without a fork):** all authorized keys are valid to
  produce from round `PULSE_MINER_FALLBACK_ROUNDS` (=2) onward. To avoid two miners producing the same height
  simultaneously, give each miner a small **local** start-delay (primary maple = 0; secondary OCI = +k rounds)
  so the secondary only mines if the primary hasn't. This delay is a per-node runtime flag (block *validity*
  stays "valid from round 2"), so it needs NO hardfork to change. If both do race, normal fork-choice resolves
  it in a block or two — acceptable for survival mode.
- The `voter_index=0xFFFF` sentinel stays; verify just checks the sig against the pubkey SET instead of one key.

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
