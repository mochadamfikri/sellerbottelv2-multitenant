"""Tests for stage3_execute.py CLI argument parsing and safety guards.

These tests validate CLI parsing and safety validation logic WITHOUT touching real databases.
All database-touching behavior is tested in test_idse_stage3_migration.py.
"""
import pytest


def test_parse_args_defaults_to_dry_run():
    """CLI should default to --dry-run mode when no flags are passed."""
    from stage3_execute import parse_args
    
    args = parse_args([])
    
    assert args.dry_run is True
    assert args.apply is False
    assert args.confirm_idse_stage3 is False
    assert args.resume is False


def test_parse_args_requires_both_apply_and_confirm_for_real_writes():
    """Real writes require BOTH --apply AND --confirm-idse-stage3."""
    from stage3_execute import parse_args
    
    args_apply_only = parse_args(["--apply"])
    args_confirm_only = parse_args(["--confirm-idse-stage3"])
    args_both = parse_args(["--apply", "--confirm-idse-stage3"])
    
    assert args_apply_only.apply is True
    assert args_apply_only.confirm_idse_stage3 is False
    
    assert args_confirm_only.apply is False
    assert args_confirm_only.confirm_idse_stage3 is True
    
    assert args_both.apply is True
    assert args_both.confirm_idse_stage3 is True


def test_parse_args_accepts_resume_flag():
    """CLI should accept --resume flag for resuming after target has docs."""
    from stage3_execute import parse_args
    
    args = parse_args(["--resume"])
    
    assert args.resume is True


def test_validate_environment_rejects_production():
    """Production environment must be rejected unconditionally."""
    from stage3_execute import validate_environment, SafetyError
    
    with pytest.raises(SafetyError, match="production"):
        validate_environment("production")
    
    with pytest.raises(SafetyError, match="production"):
        validate_environment("PRODUCTION")
    
    with pytest.raises(SafetyError, match="production"):
        validate_environment("prod")


def test_validate_environment_accepts_development_and_test():
    """Development and test environments should be accepted."""
    from stage3_execute import validate_environment
    
    # Should not raise
    validate_environment("development")
    validate_environment("test")
    validate_environment("DEVELOPMENT")
    validate_environment("TEST")


def test_validate_uri_rejects_port_27017():
    """Port 27017 must be rejected unconditionally."""
    from stage3_execute import validate_uri, SafetyError
    
    with pytest.raises(SafetyError, match="27017"):
        validate_uri("mongodb://localhost:27017/any_database")
    
    with pytest.raises(SafetyError, match="27017"):
        validate_uri("mongodb://127.0.0.1:27017/forbidden")
    
    with pytest.raises(SafetyError, match="27017"):
        validate_uri("mongodb://user:pass@host:27017/db")


def test_validate_uri_accepts_port_27018():
    """Port 27018 (dev port) should be accepted."""
    from stage3_execute import validate_uri
    
    # Should not raise
    validate_uri("mongodb://127.0.0.1:27018")
    validate_uri("mongodb://localhost:27018/sellerbottel_dev")


def test_should_execute_migration_requires_both_flags():
    """Migration execution requires both --apply and --confirm-idse-stage3."""
    from stage3_execute import should_execute_migration
    
    assert should_execute_migration(apply=False, confirm=False) is False
    assert should_execute_migration(apply=True, confirm=False) is False
    assert should_execute_migration(apply=False, confirm=True) is False
    assert should_execute_migration(apply=True, confirm=True) is True


def test_check_target_safety_allows_empty_target():
    """Empty target database should be allowed without --resume."""
    from stage3_execute import check_target_safety
    
    empty_counts = {
        "products": 0,
        "inventory_items": 0,
        "purchases": 0,
        "deposits": 0,
    }
    
    # Should not raise
    check_target_safety(empty_counts, resume=False)


def test_check_target_safety_rejects_non_empty_target_without_resume():
    """Non-empty target should be rejected unless --resume is passed."""
    from stage3_execute import check_target_safety, SafetyError
    
    non_empty_counts = {
        "products": 5,
        "inventory_items": 0,
        "purchases": 0,
        "deposits": 0,
    }
    
    with pytest.raises(SafetyError, match="already contains"):
        check_target_safety(non_empty_counts, resume=False)


def test_check_target_safety_allows_non_empty_target_with_resume():
    """Non-empty target should be allowed when --resume is passed."""
    from stage3_execute import check_target_safety
    
    non_empty_counts = {
        "products": 5,
        "inventory_items": 10,
        "purchases": 3,
        "deposits": 2,
    }
    
    # Should not raise
    check_target_safety(non_empty_counts, resume=True)


def test_format_summary_redacts_sensitive_data():
    """Summary output should never contain actual documents or PII."""
    from stage3_execute import format_summary
    
    report = {
        "tenant_id": "idse",
        "dry_run": False,
        "collections": {
            "products": {"planned": 100, "migrated": 95, "skipped": 5},
            "purchases": {"planned": 50, "migrated": 50, "skipped": 0},
        },
        "total_planned": 150,
        "total_migrated": 145,
        "total_skipped": 5,
    }
    
    summary = format_summary(report)
    
    # Should contain counts but never actual data
    assert "100" in summary or "planned" in summary
    assert "migrated" in summary
    # Should not contain any document structure indicators
    assert "{\"_id\":" not in summary
    assert "password" not in summary.lower()
    assert "token" not in summary.lower()
