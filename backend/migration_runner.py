"""Migration rehearsal runner — dev-only, defaults to dry-run.

This module is a development skeleton for rehearsing database migrations
offline.  It must NEVER touch production data (port 27017 or live MONGO_URL).
All writes require an explicit injected writer / apply flag.
"""

from __future__ import annotations


import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence
from uuid import uuid4


class TargetSecurityError(Exception):
    """Raised when target environment or URI violates safety rules."""


@dataclass(frozen=True)
class MigrationStep:
    """One migration with injected planning and optional application behavior."""

    name: str
    version: int | str
    description: str
    plan_fn: Callable[[Any], Sequence[Any]]
    apply_fn: Optional[Callable[[Any, Sequence[Any]], Any]] = None

    @property
    def checksum(self) -> str:
        payload = {
            "description": self.description,
            "name": self.name,
            "version": str(self.version),
        }
        return _checksum(payload)


@dataclass(frozen=True)
class StepReport:
    name: str
    version: int | str
    checksum: str
    status: str
    planned_changes: list[Any]
    applied_changes: int = 0


@dataclass(frozen=True)
class MigrationReport:
    run_id: str
    environment: str
    dry_run: bool
    started_at: datetime
    finished_at: datetime
    steps: list[StepReport]
    total_planned_changes: int
    total_applied_changes: int
    checksum: str

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe run metadata for storage or review."""
        return {
            "checksum": self.checksum,
            "dry_run": self.dry_run,
            "environment": self.environment,
            "finished_at": self.finished_at.isoformat(),
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "steps": [
                {
                    "applied_changes": step.applied_changes,
                    "checksum": step.checksum,
                    "name": step.name,
                    "planned_changes": step.planned_changes,
                    "status": step.status,
                    "version": step.version,
                }
                for step in self.steps
            ],
            "total_applied_changes": self.total_applied_changes,
            "total_planned_changes": self.total_planned_changes,
        }


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class MigrationRunner:
    """Orchestrates migration steps, defaults to dry-run (no writes)."""

    def __init__(
        self,
        *,
        reader: Any = None,
        dry_run: bool = True,
        writer: Any = None,
        allow_apply: bool = False,
        target_uri: Optional[str] = None,
        environment: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
        run_id_factory: Optional[Callable[[], str]] = None,
    ):
        env = (environment or os.environ.get("ENVIRONMENT", "development")).strip().lower()
        if env == "production":
            raise TargetSecurityError("Migration runner is DEV ONLY; cannot run in production")
        if target_uri is not None and ":27017" in target_uri:
            raise TargetSecurityError("Port 27017 is prohibited for rehearsal runner")
        if not dry_run and writer is None:
            raise ValueError("writer is required when dry_run=False")
        if not dry_run and not allow_apply:
            raise ValueError("allow_apply=True is required when dry_run=False")

        self.reader = reader
        self.dry_run = dry_run
        self.writer = writer
        self.allow_apply = allow_apply
        self.target_uri = target_uri
        self.environment = env
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._run_id_factory = run_id_factory or (lambda: str(uuid4()))

    def run(self, steps: Sequence[MigrationStep]) -> MigrationReport:
        """Plan steps; only explicitly authorized non-dry runs can call a writer."""
        started_at = self._clock()
        reports: list[StepReport] = []
        for step in steps:
            planned_changes = list(step.plan_fn(self.reader))
            if self.dry_run:
                reports.append(
                    StepReport(step.name, step.version, step.checksum, "simulated", planned_changes)
                )
                continue

            if step.apply_fn is None:
                raise ValueError(f"Migration step {step.name!r} has no apply_fn")
            step.apply_fn(self.writer, planned_changes)
            reports.append(
                StepReport(
                    step.name, step.version, step.checksum, "applied", planned_changes,
                    applied_changes=len(planned_changes),
                )
            )

        finished_at = self._clock()
        total_planned = sum(len(item.planned_changes) for item in reports)
        total_applied = sum(item.applied_changes for item in reports)
        payload = {
            "dry_run": self.dry_run,
            "environment": self.environment,
            "finished_at": finished_at,
            "run_id": self._run_id_factory(),
            "started_at": started_at,
            "steps": reports,
            "total_applied_changes": total_applied,
            "total_planned_changes": total_planned,
        }
        return MigrationReport(checksum=_checksum(payload), **payload)
