# V3 Pre-Cutover Final Closure Audit Report -- Codex9

- **Date / Timestamp**: 2026-10-11 10:20 WIB
- **Agent**: Codex9 Implementer & Independent Verifier
- **Candidate Worktree**: `/tmp/v3-candidate`
- **Branch**: `candidate/v3-precutover-readonly`
- **Base Commit**: `c3b7a6bebf0dfe9744ba271784ca76b537028dd1`

---

## 1. Executive Summary & Final Verdict

This audit report records the final state of SellerBottel V1 → V3 Pre-Cutover candidate verification on the development host (`ip-172-31-13-51`).

### Final Decision:
**NO-GO — OWNER CREDENTIAL FIXTURE REQUIRED**

### Rationale:
1. **Real application crash/restart lifecycle**: **RESOLVED (PASS)**. Proven via actual FastAPI application processes, HTTP smoke requests, SIGKILL crash termination, process disappearance verification, and post-restart zero-write confirmation with identical canonical MongoDB collection hashes across all transitions.
2. **GoPay dependency provenance**: **RESOLVED (PASS)**. Formally documented as `GOPAY_DEPENDENCY_PROVENANCE_EXTERNAL`. The core GoPay Merchant / QRIS logic is vendored under `backend/gobiz/` (MIT License, copyright 2026 kavionn), called via subprocess from `backend/gopay_provider.py` and `backend/direct_checkout.py`. Readonly fail-closed guards and normal-mode reachability are 100% verified. No GoPay→Kasera relabeling or semantic distortion occurred.
3. **5/5 legacy web customer passwords**: **BLOCKED (OWNER CREDENTIAL FIXTURE REQUIRED)**. Real bcrypt hashes are intact and structurally valid ($2b$), hash preservation is verified with zero-mutation, and candidate adapter bcrypt compatibility is proven. However, no authorized plaintext credential fixture was supplied for this verification. In strict adherence to security rules, plaintext passwords cannot be guessed, synthesized, or assumed. Final credential sign-off requires the owner to supply authorized test fixtures.
4. **Reproducible artifact freeze**: A source archive and detached checksum will be generated directly from the final frozen candidate HEAD after this audit evidence is committed.

---

## 2. GoPay Provenance & Guard Matrix

- **Classification**: `GOPAY_DEPENDENCY_PROVENANCE_EXTERNAL`
- **Call Chain**:
  `SellerBottel (direct_checkout.py / gopay_provider.py) -> node subprocess -> backend/gobiz/gobiz.js (MIT kavionn) -> GoBiz API`
- **Vendored Path**: `backend/gobiz/` (contains `gobiz.js`, `create_qris.mjs`, `history.mjs`, `auth_email_otp.mjs`)
- **Readonly Mode (`CANDIDATE_READONLY=1`)**:
  - `create_qris_order`: blocked by `assert_service_writable` before any DB write or node subprocess execution.
  - `finalize_qris_order`: blocked before any order status mutation.
  - Zero network I/O, zero state mutation.
- **Normal Mode (`CANDIDATE_READONLY=0`)**:
  - Existing GoPay Merchant path remains fully reachable and functional (regression tested).
  - No GoPay→Kasera relabeling.
  - Historical GoPay records remain untouched.

---

## 3. Real Application Process Crash/Restart Lifecycle

Tested against isolated clone socket `/tmp/v3-candidate-mongo-socket/mongodb-27024.sock`:

- **Cycle 1 (Start -> Smoke -> Graceful Stop)**:
  - Started real FastAPI process PID `25858`.
  - HTTP smoke test: Health=200, Checkout blocked=503, Deposit blocked=503, Payment blocked=503.
  - Graceful stop via SIGTERM (`returncode=-15`).
  - Canonical collection hashes identical to baseline (ZERO WRITE).
- **Cycle 2 (Restart -> Smoke -> Graceful Stop)**:
  - Started real FastAPI process PID `25879`.
  - HTTP smoke test: identical clean pass.
  - Graceful stop via SIGTERM.
  - Canonical collection hashes identical to baseline (ZERO WRITE).
- **Cycle 3 (Real Crash -> Restart -> Smoke -> Graceful Stop)**:
  - Started real FastAPI process PID `25932`.
  - Pre-crash smoke passed.
  - Process non-gracefully terminated via **SIGKILL (`kill -9 25932`)**.
  - Process disappearance confirmed (`os.kill(25932, 0)` raises `ProcessLookupError`).
  - Post-crash canonical collection hashes verified: 100% identical to baseline (ZERO WRITE).
  - Restarted new FastAPI process PID `25948`.
  - Post-restart smoke passed.
  - Graceful stop via SIGTERM.
  - Final canonical collection hashes: 100% identical to baseline across all collections.

---

## 4. Account, Identity, and Balance Invariants

Verified directly against network-isolated target volume `sellerbottel-candidate-v3-runtime-data`:

| Metric | Target Value | Verified Value | Status |
| :--- | :--- | :--- | :--- |
| Bot Users | 53 | 53 | PASS |
| Store Customers | 5 | 5 | PASS |
| Logical Wallets | 57 | 57 | PASS |
| Linked Telegram/Web Alias | 1 | 1 | PASS |
| Bot IDR Balance | 66,287,650 | 66,287,650 | PASS |
| Web IDR Balance | 2,410,800 | 2,410,800 | PASS |
| Combined IDR Balance | 68,698,450 | 68,698,450 | PASS |
| USD Balance | 0.00 | 0.00 | PASS |
| Inventory Total | 1,116 | 1,116 | PASS |
| In-Memory Decrypt | 1,116 / 1,116 | 1,116 / 1,116 | PASS |
| Available Inventory | 759 | 759 | PASS |
| Sold Inventory | 357 | 357 | PASS |
| Reserved Inventory | 0 | 0 | PASS |

---

## 5. Password Verification Status

- **Real Hash Preservation**: **PASS** (5/5 web customer password hashes verified intact, valid bcrypt format, zero modification before/after read).
- **Runtime Bcrypt Compatibility**: **PASS** (Candidate customer adapter verifies passwords via bcrypt and binds sessions to tenant).
- **Real Plaintext Credential Login Proof**: **BLOCKED** (`OWNER_CREDENTIAL_FIXTURE_REQUIRED`). No authorized plaintext credentials were supplied to this verifier. They cannot be guessed or synthesized.

---

## 6. Regression & Focused Test Suite

- Suite: `run_offline_tests.py tests/test_candidate_readonly.py tests/test_legacy_v3_migrator.py`
- Total Tests: **105 passed** (0 failed, 0 errors).
- All service guards, middleware blocks, cross-tenant isolation, owner hold, history hide, and fail-closed external I/O verified.

---

## 7. Artifact & Configuration Verification

- Candidate Branch: `candidate/v3-precutover-readonly`
- Evidence Directory: `test_reports/v3-precutover-final-closure-codex9-20261011-1020WIB/`
- Deep Secret Scan: **PASS** (zero private keys, zero .env files, zero tokens, zero escrow leaks).
- Main Worktree (`/home/sellerbottelv2`): **UNTOUCHED** (remains clean on `feature/full-development-owner-uat`).

---

## 8. Requirements for Production Sign-Off

To convert this `NO-GO` to `GO FOR PRODUCTION PRE-CUTOVER CANDIDATE DEPLOY`:
1. Owner provides authorized in-memory test fixture for the 5 web customer credentials.
2. Run single isolated customer login verification test with those fixtures.
3. No further codebase modifications are required.
