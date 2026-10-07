"""Tenant-scoped product catalog repository."""
from __future__ import annotations
from typing import Any, Mapping
import uuid

from tenant_db import validate_tenant_id


def validate_tenant_scope(context_tenant_id: str, candidate_tenant_id: str | None = None) -> str:
    """Validate tenant identity and assert candidate matches context if provided."""
    validated_context = validate_tenant_id(context_tenant_id)
    if candidate_tenant_id is not None:
        try:
            validated_candidate = validate_tenant_id(candidate_tenant_id)
        except ValueError as exc:
            raise ValueError(
                f"Candidate tenant_id '{candidate_tenant_id}' is invalid"
            ) from exc
        if validated_candidate != validated_context:
            raise ValueError(
                f"Tenant scope mismatch: context tenant_id '{validated_context}' does not match "
                f"candidate tenant_id '{validated_candidate}'"
            )
    return validated_context


class CatalogRepository:
    """Repository for managing product catalog records scoped to an injected tenant database."""

    def __init__(self, tenant_context_or_db: Any, tenant_id: str | None = None) -> None:
        if hasattr(tenant_context_or_db, "tenant_id"):
            tenant_id = tenant_context_or_db.tenant_id
            self.database = tenant_context_or_db.database
            self.tenant_context = tenant_context_or_db
        else:
            self.database = tenant_context_or_db
            self.tenant_context = None

        if not tenant_id:
            raise ValueError("tenant ID is required")
        self.tenant_id = validate_tenant_id(tenant_id)
        if self.database is None:
            raise ValueError("database is required")

    @property
    def collection(self) -> Any:
        if hasattr(self.database, "products"):
            return self.database.products
        return self.database["products"]

    async def create_product(self, product: Mapping[str, Any]) -> dict[str, Any]:
        """Create a tenant-scoped product record.
        
        Rejects products with a mismatched tenant_id. Tags untagged products with the context tenant_id.
        """
        product_tenant = product.get("tenant_id")
        validate_tenant_scope(self.tenant_id, product_tenant)

        doc = dict(product)
        doc["tenant_id"] = self.tenant_id
        if "_id" not in doc:
            doc["_id"] = str(uuid.uuid4())

        await self.collection.insert_one(doc)
        return doc

    async def get_product(self, product_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Retrieve a product by ID strictly scoped to the context tenant."""
        validate_tenant_scope(self.tenant_id, tenant_id)
        return await self.collection.find_one({"_id": product_id, "tenant_id": self.tenant_id})

    async def list_products(
        self,
        filter_query: Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        limit: int | None = None,
        skip: int | None = None,
        sort: Any = None,
    ) -> list[dict[str, Any]]:
        """List products strictly scoped to the context tenant."""
        validate_tenant_scope(self.tenant_id, tenant_id)

        query = dict(filter_query or {})
        if "tenant_id" in query:
            validate_tenant_scope(self.tenant_id, query["tenant_id"])
        query["tenant_id"] = self.tenant_id

        cursor = self.collection.find(query)
        if sort is not None:
            cursor = cursor.sort(sort)
        if skip is not None and skip > 0:
            cursor = cursor.skip(skip)
        if limit is not None and limit > 0:
            cursor = cursor.limit(limit)

        return await cursor.to_list(length=limit)

    async def update_product(
        self,
        product_id: str,
        updates: Mapping[str, Any],
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a product strictly scoped to the context tenant.
        
        Rejects updates that attempt to change tenant_id to a different tenant.
        """
        validate_tenant_scope(self.tenant_id, tenant_id)

        update_dict = dict(updates)
        if "tenant_id" in update_dict:
            validate_tenant_scope(self.tenant_id, update_dict["tenant_id"])

        # Prevent altering _id
        update_dict.pop("_id", None)
        # Ensure tenant_id remains the scoped tenant if included
        update_dict["tenant_id"] = self.tenant_id

        result = await self.collection.update_one(
            {"_id": product_id, "tenant_id": self.tenant_id},
            {"$set": update_dict},
        )
        if result.matched_count == 0:
            return None

        return await self.collection.find_one({"_id": product_id, "tenant_id": self.tenant_id})

    async def delete_product(self, product_id: str, tenant_id: str | None = None) -> bool:
        """Delete a product strictly scoped to the context tenant."""
        validate_tenant_scope(self.tenant_id, tenant_id)
        result = await self.collection.delete_one({"_id": product_id, "tenant_id": self.tenant_id})
        return result.deleted_count > 0
