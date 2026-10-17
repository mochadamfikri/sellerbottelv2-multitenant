# Rollback Plan

## Current state

No implementation deployment has occurred. The active production process on `127.0.0.1:8002` was not changed.

## Development/staging rollback

1. Stop promotion immediately if any phase test, review, smoke test, or verification fails.
2. Preserve logs and test artifacts; do not delete customer, product, inventory, order, deposit, or stock-event data.
3. Revert only the phase's isolated application commit or disable its feature flag.
4. Restore the staging database from the verified pre-phase backup if a database write occurred.
5. Re-run integrity, tenant-isolation, checkout/inventory, and regression tests.
6. Verify the old application version can read the database before considering promotion.

## Production gate

Production rollback steps will be completed with an environment-specific backup/restore rehearsal before any release. No production migration or restart is authorized by this document. If a release would require downtime or a risky restart, stop and request Owner approval first.
