"""Tests for migration rehearsal runner (dev-only)."""
import pytest


class TestMigrationRunnerDefaultsToSafeMode:
    """The runner must require explicit opt-in for writes."""

    def test_runner_defaults_to_dry_run_mode(self):
        """Runner initializes with dry_run=True by default."""
        from migration_runner import MigrationRunner

        runner = MigrationRunner()

        assert runner.dry_run is True

    def test_runner_rejects_apply_mode_without_writer(self):
        """Attempting to apply (dry_run=False) without a writer raises."""
        from migration_runner import MigrationRunner

        with pytest.raises(ValueError, match="writer.*required"):
            MigrationRunner(dry_run=False)


class TestSafetyGuards:
    """Runner must enforce DEV-ONLY constraints and forbid port 27017 / prod."""

    def test_runner_rejects_target_uri_with_port_27017(self):
        """Target URI mentioning port 27017 must be blocked unconditionally."""
        from migration_runner import MigrationRunner, TargetSecurityError

        with pytest.raises(TargetSecurityError, match="27017"):
            MigrationRunner(target_uri="mongodb://localhost:27017/dev")

    def test_runner_rejects_production_environment(self, monkeypatch):
        """If ENVIRONMENT is set to production, runner must refuse to run."""
        from migration_runner import MigrationRunner, TargetSecurityError

        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(TargetSecurityError, match="[Pp]roduction"):
            MigrationRunner()


class TestMigrationRehearsalExecution:
    """Verifies dependency injection, dry-run simulation, and report generation."""

    def test_dry_run_executes_plan_without_calling_writer(self):
        """Dry-run must call plan, calculate diff, but never invoke writer."""
        from unittest.mock import MagicMock
        from migration_runner import MigrationRunner, MigrationStep

        mock_writer = MagicMock()
        mock_reader = MagicMock()
        mock_reader.get_collection.return_value = [{"_id": "1", "old_field": "val"}]

        step = MigrationStep(
            name="add_tenant_id_to_orders",
            version=1,
            description="Add tenant_id default to legacy orders",
            plan_fn=lambda reader: [{"op": "update", "id": "1", "field": "tenant_id", "value": "default"}],
            apply_fn=lambda writer, plan: writer.update("orders", plan),
        )

        runner = MigrationRunner(reader=mock_reader, writer=mock_writer, dry_run=True)
        report = runner.run([step])

        # Writer was NEVER called in dry-run
        mock_writer.update.assert_not_called()
        assert report.dry_run is True
        assert report.total_planned_changes == 1
        assert report.total_applied_changes == 0
        assert len(report.steps) == 1
        assert report.steps[0].status == "simulated"
        assert report.steps[0].planned_changes == [{"op": "update", "id": "1", "field": "tenant_id", "value": "default"}]

    def test_report_has_reproducible_metadata_and_checksum(self):
        """A fixed clock and run id produce a stable, auditable report checksum."""
        from datetime import datetime, timezone
        from migration_runner import MigrationRunner, MigrationStep

        instant = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        step = MigrationStep(
            name="legacy-orders",
            version="2026.10.04",
            description="Rehearse legacy order updates",
            plan_fn=lambda reader: [{"id": "order-1"}],
        )

        runner = MigrationRunner(
            clock=lambda: instant,
            run_id_factory=lambda: "rehearsal-001",
            environment="development",
        )
        first = runner.run([step])
        second = runner.run([step])

        assert first.run_id == "rehearsal-001"
        assert first.started_at == instant
        assert first.finished_at == instant
        assert len(first.checksum) == 64
        assert first.checksum == second.checksum
        assert len(first.steps[0].checksum) == 64

    def test_report_serializes_run_metadata_and_step_checksums(self):
        """Reports are portable dictionaries without losing audit fields."""
        from datetime import datetime, timezone
        from migration_runner import MigrationRunner, MigrationStep

        instant = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        report = MigrationRunner(
            clock=lambda: instant,
            run_id_factory=lambda: "rehearsal-serialization",
        ).run([
            MigrationStep(
                name="report-step",
                version=1,
                description="Verify report serialization",
                plan_fn=lambda reader: [{"id": "1"}],
            )
        ])

        payload = report.to_dict()

        assert payload["run_id"] == "rehearsal-serialization"
        assert payload["dry_run"] is True
        assert payload["started_at"] == "2026-10-04T12:00:00+00:00"
        assert payload["checksum"] == report.checksum
        assert payload["steps"][0]["checksum"] == report.steps[0].checksum
        assert payload["steps"][0]["planned_changes"] == [{"id": "1"}]


class TestApplyAuthorization:
    def test_apply_mode_requires_explicit_apply_flag_even_with_writer(self):
        """Writer injection alone must never enable writes."""
        from migration_runner import MigrationRunner

        with pytest.raises(ValueError, match="allow_apply=True"):
            MigrationRunner(dry_run=False, writer=object())

    def test_explicit_apply_calls_injected_writer_and_reports_result(self):
        """The only write path is an explicit injected writer plus apply flag."""
        from unittest.mock import MagicMock
        from migration_runner import MigrationRunner, MigrationStep

        writer = MagicMock()
        step = MigrationStep(
            name="controlled-write",
            version=1,
            description="Test-only controlled write",
            plan_fn=lambda reader: [{"id": "1"}, {"id": "2"}],
            apply_fn=lambda injected_writer, changes: injected_writer.apply(changes),
        )

        report = MigrationRunner(
            dry_run=False, allow_apply=True, writer=writer, environment="development"
        ).run([step])

        writer.apply.assert_called_once_with([{"id": "1"}, {"id": "2"}])
        assert report.steps[0].status == "applied"
        assert report.total_applied_changes == 2


