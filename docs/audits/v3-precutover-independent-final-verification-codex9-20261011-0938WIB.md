# V3 Pre-Cutover Independent Final Verification -- Codex9

- Timestamp: 2026-10-11 09:38 WIB
- Candidate worktree: `/tmp/v3-candidate`
- Branch: `candidate/v3-precutover-readonly`
- Candidate HEAD at verification: `e04df6aa73777cb0fd24c5e5e0b8d6d89d5fc742`
- Scope: independent re-verification; implementer report treated as untrusted assertion.

## Verified Independently

- Worktree identity: expected branch, expected worktree, and clean Git status at the start of verification.
- Candidate ancestry: base commit `c3b7a6bebf0dfe9744ba271784ca76b537028dd1` is the merge-base.
- Config checksums exactly match recorded values for `backend/config.py` and `backend/candidate_readonly.py`.
- Artifact checksum matches the named archive for commit `7719faf51c2963cc95d47fd02df8420692d8b9b9`.
- Deep source scan found no `.env`, private escrow material, literal provider token, or persisted inventory encryption key. The three recorded filename matches are non-secret placeholder/harness/documentation references.
- Clone isolation: `sellerbottel-candidate-v3-runtime` is `network=none`, `restart=no`, and exposes no ports. Rehearsal source container is stopped.
- Real clone identity/account data:
  - 53 bot users; 5 web customers.
  - 1 linked Telegram/web alias; 57 logical wallets.
  - Bot IDR 66,287,650; Web IDR 2,410,800; combined IDR 68,698,450; USD 0.
  - 5/5 web records contain bcrypt-format password hashes; hashes were unchanged across independent reads.
- Isolated in-memory inventory decrypt: 1,116/1,116 successful; status distribution 759 available / 357 sold / 0 reserved. No key or plaintext was written or logged.
- QRIS/GoPay/service-level controls: focused independent guard suite passed, including readonly blocking and normal-mode QRIS reachability, owner hold, history hide, and cross-tenant middleware coverage.
- Full candidate + migration suite rerun independently: 105 passed.
- FastAPI readonly lifespan against clone passed; workers and index/settings initialization were skipped.
- Real clone hash drill rerun: documented collection hashes/counts remained identical across its three read cycles.

## Findings Blocking GO

1. **Controlled crash/restart was not independently proven.** `tools/real_data_3cycle_drill.py` labels cycle 3 as `Simulated crash (just re-read)` and performs another `smoke_reads()` call; it never starts an application process, terminates it, then restarts it. The required controlled crash/start/stop/restart gate therefore remains unproven.
2. **Five real legacy password logins were not independently proven.** The available clone proves five bcrypt-format hashes and zero mutation during read verification, but no authorized real test passwords or credential-verification fixture was provided for an independent 5/5 authentication test. Hash integrity is not equivalent to successful credential login.
3. **Frozen artifact is not anchored to the current candidate HEAD.** The archived artifact verifies commit `7719faf...`, whereas current candidate HEAD is `e04df6a...`. The latter only records artifact metadata, but the submitted final-candidate artifact cannot be verified as an archive of the final HEAD.

## Required Remediation Before Re-Verification

- Perform and preserve evidence for a real application process lifecycle: start FastAPI in readonly mode against the clone, smoke, graceful stop, restart, controlled termination, restart, smoke, graceful stop; compare canonical hashes before/after each transition.
- Provide an authorized independent mechanism to exercise the five existing legacy password credentials without revealing or persisting passwords; verify each login and before/after password-hash equality.
- Freeze one final commit, create archive from that exact commit, then record its checksum without declaring a later metadata-only commit to be the frozen candidate; alternatively attach checksum/signature outside the source commit.

## Final Result

NO-GO
