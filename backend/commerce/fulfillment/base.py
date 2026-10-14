from dataclasses import dataclass
from typing import Any, Callable, Awaitable


@dataclass
class FulfillmentContext:
    tenant_id: str
    database: Any
    order: dict
    item: dict
    execute: Callable[[], Awaitable[bool]] | None = None


class FulfillmentHandler:
    async def process(self, context: FulfillmentContext) -> str:
        raise NotImplementedError
