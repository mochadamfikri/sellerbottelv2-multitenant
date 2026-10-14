import os
import socket
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / '.migration-private'
SOCKET = PRIVATE / 'socket' / 'mongodb-27021.sock'
PLATFORM = 'sellerbottel_migration_platform'
AUDIT = 'sellerbottel_migration_audit'
ARCHIVE = 'sellerbottel_migration_archive'
PROFILE = os.environ.get('SELLER_MIGRATION_PROFILE', 'synthetic')
if PROFILE not in ('synthetic', 'offline-real'):
    raise RuntimeError('MIGRATION_PROFILE_REJECTED')
if PROFILE == 'offline-real':
    SOCKET = PRIVATE / 'real-v3' / 'socket' / 'mongodb-27023.sock'
    PLATFORM = 'sellerbottel_real_rehearsal_platform'
    AUDIT = 'sellerbottel_real_rehearsal_migration'
    ARCHIVE = 'sellerbottel_real_rehearsal_archive'
FORBIDDEN_ENV = ('TELEGRAM_TOKEN', 'BOT2_TELEGRAM_TOKEN', 'TELEGRAM_WEBHOOK_SECRET',
                 'GOPAY_PASSWORD', 'GOPAY_EMAIL', 'SMTP_PASSWORD', 'KASERA_API_KEY',
                 'MONGO_URL', 'DATABASE_URL', 'INVENTORY_ENCRYPTION_KEY', 'TG_SESSION_KEY')

class MigrationError(Exception):
    """Messages are fixed safe codes, never source values or connection errors."""


def require(condition, code):
    if not condition:
        raise MigrationError(code)


def private_file(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), 'PRIVATE_FILE_REQUIRED')
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, 'PRIVATE_FILE_MODE_0600_REQUIRED')
    return path


def guard_environment():
    require(not any(os.environ.get(k) for k in FORBIDDEN_ENV), 'LIVE_OR_SHARED_ENV_REJECTED')
    require(os.environ.get('ENVIRONMENT', '') != 'production', 'PRODUCTION_REJECTED')


def isolated_namespace():
    return (os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net')
            and {name for _,name in socket.if_nameindex()} <= {'lo'})


def block_network():
    """Defense in depth: exact Unix Mongo socket only, never TCP/DNS/SMTP."""
    original = socket.socket.connect
    def connect(sock, address):
        require(sock.family == socket.AF_UNIX and str(address) == str(SOCKET), 'EXTERNAL_IO_BLOCKED')
        return original(sock, address)
    socket.socket.connect = connect
    def denied(*args, **kwargs):
        raise MigrationError('EXTERNAL_IO_BLOCKED')
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied


def allowed_databases(owner):
    import re
    from uuid import UUID
    require(owner.get('approved') is True, 'OWNERSHIP_APPROVAL_REQUIRED')
    require(owner.get('platform_database') == PLATFORM, 'PLATFORM_DATABASE_REJECTED')
    slug = owner.get('tenant_slug', '')
    require(bool(re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', slug)), 'SLUG_REJECTED')
    prefix = 'sellerbottel_real_rehearsal_tenant_' if PROFILE == 'offline-real' else 'sellerbottel_migration_legacy_'
    expected = prefix + slug.replace('-', '_')
    if PROFILE == 'offline-real':
        require(owner.get('runtime_enabled') is False and owner.get('rehearsal_only') is True, 'REAL_RUNTIME_MUST_BE_DISABLED')
    require(owner.get('database_name') == expected, 'TENANT_DATABASE_REJECTED')
    try:
        require(str(UUID(owner['tenant_uuid'])) == owner['tenant_uuid'], 'TENANT_UUID_REQUIRED')
    except (KeyError, ValueError, TypeError):
        raise MigrationError('TENANT_UUID_REQUIRED') from None
    for key in ('legacy_admin_id', 'platform_principal', 'tenant_owner_principal', 'bot_numeric_id',
                'source_machine', 'source_database', 'allowed_domains'):
        require(owner.get(key) is not None, 'OWNERSHIP_INCOMPLETE')
    require(owner['source_database'] == 'sellerbottel', 'SOURCE_DATABASE_REJECTED')
    require(isinstance(owner['bot_numeric_id'], int) and not isinstance(owner['bot_numeric_id'], bool) and owner['bot_numeric_id'] > 0, 'BOT_ID_REQUIRED')
    require(isinstance(owner['allowed_domains'], list) and all(d.endswith('.invalid') for d in owner['allowed_domains']), 'PRODUCTION_DOMAIN_REJECTED')
    return {PLATFORM, expected, AUDIT, ARCHIVE}
