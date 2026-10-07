"""IDSE tenant metadata and initialization helper.

IDSE (the existing store) is represented as a normal first-party tenant
with a 'lifetime' plan, not a hard-coded fork.
"""

from tenant_db import tenant_database_name

# IDSE tenant constants
IDSE_TENANT_ID = "idse"
IDSE_TENANT_NAME = "IDSE Digital Market"
IDSE_DEFAULT_PLAN = "lifetime"


def get_idse_tenant_metadata() -> dict[str, object]:
    """Return canonical IDSE tenant definition.
    
    Returns:
        Dictionary with slug, name, plan, status, and database_name.
    """
    return {
        "slug": IDSE_TENANT_ID,
        "name": IDSE_TENANT_NAME,
        "plan": IDSE_DEFAULT_PLAN,
        "status": "active",
        "database_name": tenant_database_name(IDSE_TENANT_ID),
    }


def ensure_idse_tenant(registry, provisioning_fn=None) -> dict[str, object]:
    """Idempotently ensure IDSE tenant exists in registry.
    
    Checks if 'idse' tenant exists in registry; if not, registers it with
    plan='lifetime', status='active', database_name=tenant_database_name('idse')
    and runs provisioning if provided.
    
    Args:
        registry: TenantRegistry instance to register with.
        provisioning_fn: Optional callable(tenant) to run for new tenant provisioning.
    
    Returns:
        The IDSE tenant dictionary with all metadata.
    """
    existing = registry.get_tenant(IDSE_TENANT_ID)
    
    if existing is not None:
        # Tenant already exists, return as-is
        return existing
    
    # Create new IDSE tenant with plan='lifetime'
    tenant = registry.create_tenant(
        slug=IDSE_TENANT_ID, name=IDSE_TENANT_NAME, plan=IDSE_DEFAULT_PLAN
    )
    
    # Run provisioning if provided
    if provisioning_fn is not None:
        provisioning_fn(tenant)
    
    return tenant
