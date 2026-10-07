# Phase 2 Tenant Memberships Implementation

## Summary

Implemented persistent tenant memberships with role-based authorization using strict TDD.

## Files Modified

### `backend/platform_rbac.py`
- Added `add_tenant_member(db, tenant_id, user_id, role)` - Create/update membership
- Added `get_tenant_membership(db, tenant_id, user_id)` - Retrieve single membership
- Added `list_tenant_members(db, tenant_id)` - List all tenant members
- Added `remove_tenant_member(db, tenant_id, user_id)` - Remove membership
- Added `require_tenant_role(tenant_id, min_role)` - Dependency factory for role enforcement
- Updated `require_tenant_membership(tenant_id)` - Now enforces viewer role minimum
- Defined tenant role hierarchy: viewer < operator < admin < owner

### `backend/db.py`
- Added indexes for `tenant_memberships` collection:
  - Unique compound index on `(tenant_id, user_id)`
  - Index on `(tenant_id, created_at)` for listing
  - Index on `user_id` for reverse lookups

### `backend/tests/test_platform_rbac.py`
- Removed obsolete Phase 1 stub tests (now replaced by Phase 2 implementation)

### `backend/tests/test_platform_rbac_memberships.py` (NEW)
- 8 comprehensive tests covering all membership operations
- Tests role validation, CRUD operations, scoping, and authorization

## Schema

**Collection:** `tenant_memberships`

```javascript
{
  _id: UUID string,
  tenant_id: string,
  user_id: string,
  role: "tenant_viewer" | "tenant_operator" | "tenant_admin" | "tenant_owner",
  created_at: datetime (UTC),
  updated_at: datetime (UTC)
}
```

## Role Hierarchy

1. `tenant_viewer` - Read-only access
2. `tenant_operator` - Can modify resources
3. `tenant_admin` - Can manage settings
4. `tenant_owner` - Full control

Higher roles inherit lower role permissions.

## Test Coverage

All 12 tests passing:
- 4 platform admin tests (existing)
- 8 tenant membership tests (new)

Run with:
```bash
python run_offline_tests.py tests/test_platform_rbac.py tests/test_platform_rbac_memberships.py
```

## TDD Compliance

✅ RED phase: Tests written first, verified failing (ImportError)
✅ GREEN phase: Minimal implementation, all tests pass
✅ No regressions: Existing platform admin tests still pass
✅ Clean implementation: No refactoring needed
