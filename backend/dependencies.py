"""Shared FastAPI dependencies for platform services."""
from __future__ import annotations

import os
from functools import lru_cache

from db import client
from tenant_registry import MongoTenantRegistry


@lru_cache(maxsize=1)
def get_tenant_registry() -> MongoTenantRegistry:
    """Provide the persistent registry backed by the configured Mongo client."""
    return MongoTenantRegistry(environment=os.environ, client=client)
