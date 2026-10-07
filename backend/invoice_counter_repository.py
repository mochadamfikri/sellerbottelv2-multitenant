"""Async repository for per-tenant invoice counters with atomic increment."""

from typing import Any
from pymongo import ReturnDocument

from tenant_db import validate_tenant_id


class InvoiceCounterRepository:
    """Manages per-tenant invoice counters with atomic operations."""

    def __init__(self, database: Any):
        if database is None:
            raise ValueError("database is required")
        self.database = database

    async def initialize_counter(self, tenant_id: str, counter_name: str, legacy_max: int) -> None:
        """Initialize a counter from a legacy maximum value.
        
        Sets the counter to legacy_max so the next increment returns legacy_max + 1.
        Safe to call multiple times - only sets if the counter doesn't exist.
        """
        clean_tenant = validate_tenant_id(tenant_id)
        if not counter_name or not isinstance(counter_name, str):
            raise ValueError("counter_name must be a non-empty string")
        if not isinstance(legacy_max, int) or legacy_max < 0:
            raise ValueError("legacy_max must be a non-negative integer")

        await self.database.counters.update_one(
            {"tenant_id": clean_tenant, "counter_name": counter_name},
            {"$setOnInsert": {"value": legacy_max}},
            upsert=True
        )

    async def get_next_counter(self, tenant_id: str, counter_name: str) -> int:
        """Atomically increment and return the next counter value.
        
        If counter doesn't exist, initializes to 0 then increments to 1.
        """
        clean_tenant = validate_tenant_id(tenant_id)
        if not counter_name or not isinstance(counter_name, str):
            raise ValueError("counter_name must be a non-empty string")

        result = await self.database.counters.find_one_and_update(
            {"tenant_id": clean_tenant, "counter_name": counter_name},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return result["value"]
