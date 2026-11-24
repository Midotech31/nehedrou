"""Check that application and migration routes share a PostgreSQL database."""
import secrets

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connections


def try_database_lock(route, key):
    with route.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '3000ms'")
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s::bigint)', [key])
        return cursor.fetchone()[0] is True


def database_routes_match(runtime, migration):
    """Exercise one transaction-scoped lock through two transient connections.

    The migration route must fail to acquire the key while the runtime holds
    it, then acquire it after a synchronous rollback. No schema or rows change.
    This uses transaction locks so a transaction pooler can pin each backend.
    """
    key = secrets.randbits(63)
    try:
        runtime.set_autocommit(False)
        migration.set_autocommit(False)
        if not try_database_lock(runtime, key) or try_database_lock(migration, key):
            return False
        runtime.rollback()
        return try_database_lock(migration, key)
    finally:
        try:
            migration.close()
        finally:
            runtime.close()


def verify_migration_database(migration_host):
    """Reject unverified alternate migration routes before running migrate."""
    default = connections['default']
    if default.vendor != 'postgresql':
        raise ImproperlyConfigured('An alternate migration host requires a PostgreSQL application database.')
    if migration_host == default.settings_dict['HOST']:
        return

    runtime = default.copy(alias='startup_runtime')
    migration = default.copy(alias='startup_migration')
    migration.settings_dict['HOST'] = migration_host
    try:
        matches = database_routes_match(runtime, migration)
    except (DatabaseError, OSError):
        raise ImproperlyConfigured('Could not verify the PostgreSQL migration database before migration.') from None
    if not matches:
        raise ImproperlyConfigured('The PostgreSQL application and migration routes did not identify the same database.')
