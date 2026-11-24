"""Private, bounded erasure-reference comparison. Never authorizes reopening."""
from contextlib import contextmanager
from datetime import datetime, timezone as datetime_timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone

from core.backups import cipher, private_path, verify_backup

SCHEMA = 'nehedrou-erasure-checkpoint-v1'
MAX_PAIRS = 10000
MAX_PLAINTEXT = 1024 * 1024
MAX_CIPHERTEXT = 2 * 1024 * 1024
FIELDS = {'schema', 'archive_sha256', 'capture_database_sha256', 'captured_at', 'operator_cutoff', 'pairs'}
SCOPE = ('Known recorded references on the explicitly selected database only. '
    'History completeness, authentic source, independent secured custody, source lineage, '
    'quiescence and the exact restored target require separate operator verification. '
    'This result never authorizes reopening or return to service.')


def require(ok, code):
    if not ok:
        raise CommandError(code)


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-fA-F]{64}', value) is not None,
            'ERASURE_CHECKPOINT_INVALID_SHA256')
    return value.lower()


def instant(value):
    try:
        require(isinstance(value, str) and 0 < len(value) <= 64, 'ERASURE_CHECKPOINT_INVALID_TIMESTAMP')
        parsed = datetime.fromisoformat(value)
        require(parsed.utcoffset() is not None, 'ERASURE_CHECKPOINT_AWARE_TIMESTAMP_REQUIRED')
        return parsed.astimezone(datetime_timezone.utc)
    except (ValueError, OverflowError):
        raise CommandError('ERASURE_CHECKPOINT_INVALID_TIMESTAMP') from None


def identity(value):
    try:
        require(isinstance(value, (str, uuid.UUID)), 'ERASURE_CHECKPOINT_INVALID_REFERENCE')
        require(0 < len(str(value)) <= 64, 'ERASURE_CHECKPOINT_INVALID_REFERENCE')
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        raise CommandError('ERASURE_CHECKPOINT_INVALID_REFERENCE') from None


def pairs_from(rows):
    require(isinstance(rows, (list, tuple)) and len(rows) <= MAX_PAIRS,
            'ERASURE_CHECKPOINT_REFERENCE_LIMIT')
    result = set()
    for row in rows:
        require(isinstance(row, (list, tuple)) and len(row) == 2,
                'ERASURE_CHECKPOINT_INVALID_REFERENCE')
        result.add((identity(row[0]), identity(row[1])))
    return result


def database_fingerprint(coordinates):
    return hashlib.sha256(json.dumps(coordinates, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


class Reader:
    def __init__(self, conn, vendor, identity_sha256):
        self.conn, self.vendor, self.identity_sha256 = conn, vendor, identity_sha256

    def rows(self, query, parameters=(), limit=MAX_PAIRS + 1):
        cursor = self.conn.cursor()
        try:
            cursor.execute(query.replace('%s', '?') if self.vendor == 'sqlite' else query, parameters)
            return cursor.fetchmany(limit)
        finally:
            cursor.close()


@contextmanager
def selected_database(expected_database, expected_host=None, expected_port=None):
    config = settings.DATABASES['default']
    engine = config.get('ENGINE', '')
    conn = None
    try:
        if engine.endswith('sqlite3'):
            require(not expected_host and not expected_port, 'ERASURE_CHECKPOINT_SQLITE_HOST_NOT_USED')
            try:
                configured, expected = Path(config['NAME']), Path(expected_database)
                require(configured.is_absolute() and expected.is_absolute(),
                        'ERASURE_CHECKPOINT_ABSOLUTE_SQLITE_IDENTITY_REQUIRED')
                require(configured.resolve(strict=True) == expected.resolve(strict=True) and configured.is_file(),
                        'ERASURE_CHECKPOINT_DATABASE_IDENTITY_MISMATCH')
                database = configured.resolve(strict=True)
            except (OSError, TypeError, KeyError):
                raise CommandError('ERASURE_CHECKPOINT_DATABASE_IDENTITY_MISMATCH') from None
            # mode=ro must never create a missing selected database.
            conn = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            reader = Reader(conn, 'sqlite', database_fingerprint(
                {'engine': 'sqlite', 'database': os.path.normcase(str(database))}))
        elif engine.endswith('postgresql'):
            name = config.get('NAME')
            require(isinstance(name, str) and name and '=' not in name and '\x00' not in name
                    and not name.startswith(('postgres:', 'postgresql:')) and name == expected_database,
                    'ERASURE_CHECKPOINT_DATABASE_IDENTITY_MISMATCH')
            require(isinstance(expected_host, str) and expected_host and config.get('HOST') == expected_host,
                    'ERASURE_CHECKPOINT_HOST_IDENTITY_MISMATCH')
            try:
                port = int(config.get('PORT') or 5432)
                require(expected_port is not None and 1 <= port <= 65535 and int(expected_port) == port,
                        'ERASURE_CHECKPOINT_PORT_IDENTITY_MISMATCH')
            except (ValueError, TypeError):
                raise CommandError('ERASURE_CHECKPOINT_PORT_IDENTITY_MISMATCH') from None
            require(config.get('USER') and config.get('PASSWORD'), 'ERASURE_CHECKPOINT_EXPLICIT_CREDENTIALS_REQUIRED')
            require(not any(os.getenv(key) for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE')),
                    'ERASURE_CHECKPOINT_AMBIENT_ROUTE_REFUSED')
            import psycopg
            conn = psycopg.connect(host=expected_host, port=port, dbname=name,
                user=config['USER'], password=config['PASSWORD'], connect_timeout=5,
                sslmode=config.get('OPTIONS', {}).get('sslmode', 'prefer'),
                options='-c default_transaction_read_only=on')
            conn.execute('SET TRANSACTION READ ONLY')
            conn.execute("SET LOCAL statement_timeout='5s'")
            reader = Reader(conn, 'postgresql', database_fingerprint({'engine': 'postgresql',
                'database': name, 'host': expected_host.casefold().rstrip('.'), 'port': port}))
            require(reader.rows('SELECT current_database()', limit=1) == [(name,)],
                    'ERASURE_CHECKPOINT_DATABASE_IDENTITY_MISMATCH')
        else:
            raise CommandError('ERASURE_CHECKPOINT_UNSUPPORTED_DATABASE')
        # Both tables and migration history must exist. A blank/uninitialized
        # selection must not be mistaken for absence of known erased children.
        apps = {row[0] for row in reader.rows(
            "SELECT DISTINCT app FROM django_migrations WHERE app IN ('core','care')", limit=3)}
        require(apps == {'core', 'care'}, 'ERASURE_CHECKPOINT_UNINITIALIZED_DATABASE')
        reader.rows('SELECT organization_id,object_id FROM core_auditevent LIMIT 0')
        reader.rows('SELECT id,organization_id FROM care_child LIMIT 0')
        yield reader
    except CommandError:
        raise
    except Exception:
        # Backend errors may contain private paths, credentials or SQL details.
        raise CommandError('ERASURE_CHECKPOINT_DATABASE_READ_FAILED') from None
    finally:
        if conn is not None:
            conn.close()


def report_base(archive_sha256, checkpoint_sha256, cutoff):
    return {'archive_sha256': archive_sha256, 'checkpoint_sha256': checkpoint_sha256,
        'operator_cutoff': cutoff.isoformat(), 'history_completeness_verified': False,
        'source_authenticity_verified': False, 'selected_database_lineage_verified': False,
        'return_to_service_authorized': False, 'scope': SCOPE}


def capture(archive, destination, cutoff, expected_database, expected_host=None, expected_port=None):
    verified = verify_backup(archive)
    cutoff = instant(cutoff)
    # Conservative timestamp before opening the transaction/first audit snapshot.
    captured_at = timezone.now().astimezone(datetime_timezone.utc)
    require(cutoff <= captured_at, 'ERASURE_CHECKPOINT_CUTOFF_AFTER_CAPTURE')
    require(not Path(destination).is_symlink(), 'ERASURE_CHECKPOINT_SYMLINK_REFUSED')
    destination = private_path(destination)
    require(not destination.exists(), 'ERASURE_CHECKPOINT_NEW_PRIVATE_PATH_REQUIRED')
    with selected_database(expected_database, expected_host, expected_port) as reader:
        require(reader.vendor == verified['database_engine'], 'ERASURE_CHECKPOINT_ENGINE_MISMATCH')
        rows = reader.rows('SELECT DISTINCT organization_id,object_id FROM core_auditevent '
            'WHERE action=%s ORDER BY organization_id,object_id', ('child.erased',))
        pairs = pairs_from(rows)
        capture_database_sha256 = reader.identity_sha256
    payload = {'schema': SCHEMA, 'archive_sha256': verified['sha256'],
        'capture_database_sha256': capture_database_sha256,
        'captured_at': captured_at.isoformat(), 'operator_cutoff': cutoff.isoformat(),
        'pairs': sorted(pairs)}
    plaintext = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    require(len(plaintext) <= MAX_PLAINTEXT, 'ERASURE_CHECKPOINT_PLAINTEXT_LIMIT')
    token = cipher().encrypt(plaintext)
    require(len(token) <= MAX_CIPHERTEXT, 'ERASURE_CHECKPOINT_CIPHERTEXT_LIMIT')
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            output.write(token)
    except OSError:
        raise CommandError('ERASURE_CHECKPOINT_PRIVATE_WRITE_FAILED') from None
    return {**report_base(verified['sha256'], hashlib.sha256(token).hexdigest(), cutoff),
        'status': 'captured_references', 'captured_at': captured_at.isoformat(), 'reference_pairs': len(pairs)}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'ERASURE_CHECKPOINT_DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def load_checkpoint(path, expected_sha256, archive_sha256, cutoff):
    expected_sha256 = digest(expected_sha256)
    try:
        with private_path(path).open('rb') as source:
            token = source.read(MAX_CIPHERTEXT + 1)
        require(len(token) <= MAX_CIPHERTEXT, 'ERASURE_CHECKPOINT_CIPHERTEXT_LIMIT')
        require(hashlib.sha256(token).hexdigest() == expected_sha256, 'ERASURE_CHECKPOINT_SHA256_MISMATCH')
        plaintext = cipher().decrypt(token)
        require(len(plaintext) <= MAX_PLAINTEXT, 'ERASURE_CHECKPOINT_PLAINTEXT_LIMIT')
        payload = json.loads(plaintext, object_pairs_hook=unique_object)
    except (OSError, InvalidToken, ValueError, TypeError, UnicodeError, RecursionError):
        raise CommandError('ERASURE_CHECKPOINT_INVALID_ENCRYPTED_INPUT') from None
    require(isinstance(payload, dict) and set(payload) == FIELDS and payload['schema'] == SCHEMA,
            'ERASURE_CHECKPOINT_INVALID_SCHEMA')
    require(digest(payload['archive_sha256']) == archive_sha256, 'ERASURE_CHECKPOINT_ARCHIVE_MISMATCH')
    captured_at, declared_cutoff = instant(payload['captured_at']), instant(payload['operator_cutoff'])
    now = timezone.now().astimezone(datetime_timezone.utc)
    require(declared_cutoff <= captured_at <= now and cutoff <= now,
            'ERASURE_CHECKPOINT_INVALID_TIME_RANGE')
    require(declared_cutoff >= cutoff and captured_at >= cutoff, 'ERASURE_CHECKPOINT_STALE_HISTORY')
    return pairs_from(payload['pairs']), captured_at, expected_sha256, digest(payload['capture_database_sha256'])


def check(archive, checkpoint, expected_sha256, cutoff, expected_database,
          expected_host=None, expected_port=None):
    verified = verify_backup(archive)
    cutoff = instant(cutoff)
    pairs, captured_at, checkpoint_sha256, capture_database_sha256 = load_checkpoint(
        checkpoint, expected_sha256, verified['sha256'], cutoff)
    actual = {}
    with selected_database(expected_database, expected_host, expected_port) as reader:
        require(reader.vendor == verified['database_engine'], 'ERASURE_CHECKPOINT_ENGINE_MISMATCH')
        require(reader.identity_sha256 != capture_database_sha256, 'ERASURE_CHECKPOINT_CAPTURE_DATABASE_REFUSED')
        require(not pairs or bool(reader.rows('SELECT 1 FROM care_child LIMIT 1', limit=1)),
                'ERASURE_CHECKPOINT_NONEMPTY_REFERENCES_EMPTY_TARGET')
        dossiers = sorted({dossier for _cabinet, dossier in pairs})
        for start in range(0, len(dossiers), 256):
            batch = dossiers[start:start + 256]
            values = [uuid.UUID(value).hex if reader.vendor == 'sqlite' else uuid.UUID(value) for value in batch]
            rows = reader.rows('SELECT id,organization_id FROM care_child WHERE id IN (' +
                ','.join(['%s'] * len(values)) + ')', values, limit=257)
            require(len(rows) <= len(batch), 'ERASURE_CHECKPOINT_INVALID_TARGET_ROWS')
            for dossier, cabinet in rows:
                dossier, cabinet = identity(dossier), identity(cabinet)
                require(dossier not in actual, 'ERASURE_CHECKPOINT_DUPLICATE_TARGET_IDENTITY')
                actual[dossier] = cabinet
    matching = sum(actual.get(dossier) == cabinet for cabinet, dossier in pairs)
    ambiguous = sum(dossier in actual and actual[dossier] != cabinet for cabinet, dossier in pairs)
    status = ('ambiguous_scope_in_checkpoint' if ambiguous else
        'recorded_erased_pairs_present' if matching else 'no_matches_in_checkpoint')
    return {**report_base(verified['sha256'], checkpoint_sha256, cutoff), 'status': status,
        'captured_at': captured_at.isoformat(), 'reference_pairs': len(pairs),
        'matching_restored_pairs': matching, 'ambiguous_scope_pairs': ambiguous,
        'blocking': bool(matching or ambiguous)}
