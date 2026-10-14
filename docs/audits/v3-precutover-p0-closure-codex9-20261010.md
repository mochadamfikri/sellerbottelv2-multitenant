# V3 Pre-Cutover P0 Closure - Codex9

**Date:** 2026-10-10
**Candidate worktree:** `/tmp/v3-candidate`
**Candidate branch:** `candidate/v3-precutover-readonly`
**Base SHA:** `c3b7a6bebf0dfe9744ba271784ca76b537028dd1`
**Readiness:** **BLOCKED**

## Implemented (not yet independently re-verified)

- `CANDIDATE_READONLY=1` middleware blocks non-read HTTP methods by default and only permits explicit read/login paths.
- Candidate startup skips index/settings initialization, admin seeding, all listed economic workers, provider monitors, promotion runtime, service waiters, and Telegram webhook setup.
- Read-only legacy customer adapter verifies existing bcrypt hashes without rehash/write; it resolves Telegram-linked web customers to the bot wallet authority.
- Candidate customer router supplies tenant-bound HMAC sessions for read-only legacy login/profile/balance and returns deterministic `503` for history.
- Explicit candidate owner mapping rejects rehearsal placeholders and fails closed when the approved identifier is unset.
- Focused offline tests: `46 passed`; legacy migration tests: `38 passed` (the latter required the local offline runner outside the sandbox because the sandbox forbids the test's loopback socket construction before its in-process network guard executes).

## Blocking gates

1. **Actual accepted real migrated candidate runtime not exercised.** The required private isolated target was not available to this worktree; the zero-write/restart drill is synthetic `mongomock` evidence only.
2. **Service-level enforcement incomplete.** Request middleware protects HTTP routes and startup workers, but every direct economic/service entrypoint and every provider transport has not yet been individually guarded.
3. **Existing V3 customer routes are not migrated to the candidate legacy adapter.** The adapter is exposed through a candidate-only route pending integration/approval of the intended production-facing route contract.
4. **Owner held/approved mapping is not wired to every platform-owner route.** The config resolver is implemented, but the existing owner authentication flow has not been migrated to it.
5. **Historical hide policy is candidate-router-only.** Existing history endpoints have not been comprehensively catalogued and guarded.
6. **No real-data start/stop/restart hash evidence, inventory decrypt proof, or external I/O trace exists.**
7. **No clean frozen artifact is created.** Candidate changes are intentionally uncommitted until the above P0 items are satisfied; no artifact hash or secret scan can be valid yet.

## Safety

- No production host, DNS, webhook, or provider was contacted.
- No live credential was loaded.
- No accepted source snapshot or UAT database was mutated.
- The original dirty worktree's source/WIP files remain untouched; the only main-tree addition is sanitized test evidence under `test_reports/`.

## Continuation update

- Retained accepted source target was located as stopped Docker container `sellerbottel-real-v3-rehearsal-20261010`, with Docker network mode `none` and source volume `sellerbottel-real-v3-rehearsal-data-20261010`.
- A new clone volume `sellerbottel-candidate-v3-runtime-data` was created with its source mounted read-only and the copy container configured with `--network none`. The retained source volume was not mutated.
- Runtime exercise of the clone is blocked because Docker requires elevated privileges unavailable to the current sandbox. The candidate server therefore was not started against the real migrated target.
- The clone helper image was unavailable locally and Docker downloaded `alpine:latest` from the public registry before it ran. This did not contact SellerBottel production or a payment/provider endpoint, but it prevents a claim of zero external host traffic for this continuation session.

### Remaining blockers after continuation

- Gate 1 and Gate 6: actual real-data candidate runtime, before/after hashes, restart/crash, inventory decrypt, and external-I/O evidence are not complete.
- Gate 2: direct service-level guards are not complete for every economic/provider entrypoint.
- Gate 3–5: adapter/owner/history policies are not fully wired into all established V3 route contracts.
- Gate 7: no frozen candidate commit/artifact is valid while the above P0 gates remain open.
