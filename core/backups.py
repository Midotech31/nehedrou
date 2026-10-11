"""Encrypted, bounded operator backups. Restoration always targets fresh locations."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from contextlib import closing
from django.conf import settings
from django.core.management.base import CommandError

LIMIT = 64 * 1024 * 1024


def cipher():
    from cryptography.fernet import Fernet
    try:
        return Fernet(os.environ['NEHEDROU_BACKUP_KEY'].encode('ascii'))
    except (KeyError, ValueError, UnicodeError):
        raise CommandError('Set a private NEHEDROU_BACKUP_KEY. Never pass it on the command line or commit it.')


def private_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise CommandError('Use an absolute private path outside the source checkout.')
    path = path.resolve()
    if path.is_relative_to(Path(settings.BASE_DIR).resolve()) or path.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
        raise CommandError('Backup and restore targets must stay outside the source checkout and active media storage.')
    if not path.parent.is_dir():
        raise CommandError('The private parent directory must already exist.')
    return path


def pg_command(name, dbname, extra):
    config = settings.DATABASES['default']
    configured = os.environ.get('NEHEDROU_PG_BIN')
    binary = str(Path(configured) / (name + ('.exe' if os.name == 'nt' else ''))) if configured else shutil.which(name)
    if not binary or not Path(binary).is_file():
        raise CommandError('Install the matching PostgreSQL client tools or configure NEHEDROU_PG_BIN.')
    env = dict(os.environ, PGPASSWORD=str(config.get('PASSWORD','')))
    if config.get('OPTIONS', {}).get('sslmode'):
        env['PGSSLMODE'] = config['OPTIONS']['sslmode']
    args = [binary, '--host', str(os.getenv('POSTGRES_MIGRATION_HOST') or config.get('HOST') or 'localhost'), '--port', str(config.get('PORT') or 5432),
            '--username', str(config.get('USER') or ''), '--dbname', str(dbname), *extra]
    try:
        result = subprocess.run(args, env=env, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise CommandError('PostgreSQL backup/restore client unavailable or timed out. No credentials were printed.')
    if result.returncode:
        raise CommandError('PostgreSQL backup/restore failed; inspect private operator logs. No credentials were printed.')


def create_backup(destination):
    encryption = cipher()
    destination = private_path(destination)
    if destination.exists():
        raise CommandError('The destination exists. Choose a new backup filename.')
    config = settings.DATABASES['default']
    engine = 'postgresql' if config['ENGINE'].endswith('postgresql') else 'sqlite' if config['ENGINE'].endswith('sqlite3') else ''
    if not engine:
        raise CommandError('Unsupported database engine.')
    entries = {}
    with tempfile.TemporaryDirectory(prefix='nehedrou-backup-', dir=destination.parent) as directory:
        database = Path(directory) / 'database.bin'
        if engine == 'sqlite':
            source = Path(config['NAME']).resolve()
            if not source.is_file():
                raise CommandError('The source database is unavailable.')
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(database)) as snapshot:
                original.backup(snapshot)
        else:
            pg_command('pg_dump', config['NAME'], ['--format=custom','--no-owner','--no-acl','--file',str(database)])
        if database.stat().st_size > LIMIT:
            raise CommandError('This pilot backup supports at most 64 MiB of uncompressed content. Use a streaming infrastructure backup for larger data.')
        entries['database.bin'] = database.read_bytes()
        total = len(entries['database.bin'])
        if getattr(settings, 'MEDIA_STORAGE_BACKEND', 'filesystem') == 's3':
            from django.core.files.storage import default_storage
            pending, seen = [''], set()
            while pending:
                prefix = pending.pop()
                if prefix in seen or len(seen) >= 10000:
                    raise CommandError('Remote storage listing exceeded this bounded pilot backup.')
                seen.add(prefix)
                directories, files = default_storage.listdir(prefix)
                for name in directories:
                    if not name or '/' in name or name in ['.', '..'] or '\\' in name or ':' in name:
                        raise CommandError('Unsafe remote storage directory.')
                    pending.append((prefix + '/' if prefix else '') + name)
                for name in files:
                    if not name or '/' in name or name in ['.', '..'] or '\\' in name or ':' in name:
                        raise CommandError('Unsafe remote storage filename.')
                    key = (prefix + '/' if prefix else '') + name
                    if default_storage.size(key) > LIMIT - total:
                        raise CommandError('This pilot backup supports at most 64 MiB. Use a streaming infrastructure backup for larger data.')
                    with default_storage.open(key, 'rb') as file:
                        data = file.read(LIMIT - total + 1)
                    total += len(data)
                    if total > LIMIT or len(entries) >= 10000:
                        raise CommandError('Remote storage exceeded this bounded pilot backup.')
                    entries['media/' + key] = data
        else:
            media_root = Path(settings.MEDIA_ROOT).resolve()
            if media_root.exists():
                for file in sorted(media_root.rglob('*')):
                    if file.is_symlink():
                        raise CommandError('Symbolic links are not supported in media backups.')
                    if not file.is_file():
                        continue
                    if not file.resolve().is_relative_to(media_root):
                        raise CommandError('Media storage escaped its configured root.')
                    if file.stat().st_size > LIMIT - total:
                        raise CommandError('This pilot backup supports at most 64 MiB. Use a streaming infrastructure backup for larger data.')
                    with file.open('rb') as stream:
                        data = stream.read(LIMIT - total + 1)
                    total += len(data)
                    if total > LIMIT or len(entries) >= 10000:
                        raise CommandError('Media exceeded this bounded pilot backup.')
                    entries['media/' + file.relative_to(media_root).as_posix()] = data
        manifest = {'schema':'nehedrou-encrypted-backup-v1', 'database_engine':engine, 'source_database':str(config['NAME']),
                    'files':{name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in entries.items()}}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in entries.items():archive.writestr(name,data)
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False).encode('utf-8'))
        token = encryption.encrypt(buffer.getvalue())
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor,'wb') as output:output.write(token)
    return {'encrypted':True,'database_engine':engine,'file_count':len(entries),'sha256':hashlib.sha256(token).hexdigest()}


def inspect_backup(source):
    from cryptography.fernet import InvalidToken
    path = Path(source).resolve()
    if not path.is_file() or path.stat().st_size > LIMIT * 2:
        raise CommandError('Missing or oversized encrypted backup.')
    try:
        decrypted = cipher().decrypt(path.read_bytes())
        archive = zipfile.ZipFile(io.BytesIO(decrypted))
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or sum(info.file_size for info in infos) > LIMIT + 4 * 1024 * 1024:
            raise ValueError
        for name in names:
            parts = PurePosixPath(name).parts
            if not parts or name.startswith('/') or '..' in parts or '\\' in name or ':' in name or PurePosixPath(name).as_posix() != name or not (name in ['database.bin','manifest.json'] or (name.startswith('media/') and len(parts) >= 2)):
                raise ValueError
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema') != 'nehedrou-encrypted-backup-v1' or manifest.get('database_engine') not in ['sqlite','postgresql']:
            raise ValueError
        if set(manifest['files']) != set(names) - {'manifest.json'} or 'database.bin' not in names:
            raise ValueError
        entries = {name:archive.read(name) for name in manifest['files']}
        for name,data in entries.items():
            expected = manifest['files'][name]
            if expected['bytes'] != len(data) or expected['sha256'] != hashlib.sha256(data).hexdigest():
                raise ValueError
        archive.close()
    except (InvalidToken, zipfile.BadZipFile, ValueError, KeyError, TypeError, UnicodeError):
        raise CommandError('The backup key, authenticated content or file manifest is invalid. Nothing was restored.')
    return manifest, entries


def restore_backup(source, media_destination, sqlite_destination=None, postgres_database=None):
    manifest, entries = inspect_backup(source)
    media = private_path(media_destination)
    if media.exists():
        raise CommandError('Restore media into a fresh directory only.')
    if manifest['database_engine'] == 'sqlite':
        if postgres_database or not sqlite_destination:
            raise CommandError('Provide a fresh SQLite target for this backup.')
        database = private_path(sqlite_destination)
        if database == media or media.is_relative_to(database):
            raise CommandError('Database and media targets must be distinct.')
        if database.exists():
            raise CommandError('Restore SQLite into a new file only; active databases cannot be overwritten.')
        # Verify a temporary copy before creating the requested target.
        with tempfile.TemporaryDirectory(prefix='nehedrou-check-',dir=media.parent) as directory:
            temporary = Path(directory)/'snapshot.sqlite3'; temporary.write_bytes(entries['database.bin'])
            try:
                with closing(sqlite3.connect(temporary)) as connection:
                    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise CommandError('SQLite integrity verification failed.')
            except sqlite3.DatabaseError:
                raise CommandError('SQLite integrity verification failed.')
        descriptor=os.open(database,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'wb') as output:output.write(entries['database.bin'])
    else:
        if sqlite_destination or not postgres_database or postgres_database == str(settings.DATABASES['default']['NAME']) or postgres_database == manifest['source_database']:
            raise CommandError('Provide a distinct, existing empty PostgreSQL database.')
        import psycopg
        config=settings.DATABASES['default']
        with psycopg.connect(host=os.getenv('POSTGRES_MIGRATION_HOST') or config.get('HOST') or 'localhost',port=config.get('PORT') or 5432,
                user=config.get('USER'),password=config.get('PASSWORD'),dbname=postgres_database,connect_timeout=5, **({'sslmode':config['OPTIONS']['sslmode']} if config.get('OPTIONS',{}).get('sslmode') else {})) as connection:
            objects=connection.execute("SELECT 1 FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public' LIMIT 1").fetchone()
            if objects:raise CommandError('The PostgreSQL target is not empty. No restoration was attempted.')
        with tempfile.TemporaryDirectory(prefix='nehedrou-restore-',dir=media.parent) as directory:
            temporary=Path(directory)/'database.bin';temporary.write_bytes(entries['database.bin'])
            pg_command('pg_restore',postgres_database,['--exit-on-error','--single-transaction','--no-owner','--no-acl',str(temporary)])
    media.mkdir(mode=0o700)
    for name,data in entries.items():
        if not name.startswith('media/'):continue
        target=media/Path(*PurePosixPath(name).parts[1:])
        if not target.resolve().is_relative_to(media):raise CommandError('Unsafe media restoration path.')
        target.parent.mkdir(parents=True,exist_ok=True)
        descriptor=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'wb') as output:output.write(data)
    return {'restored':True,'database_engine':manifest['database_engine'],'file_count':len(entries), 'target_was_fresh':True}
