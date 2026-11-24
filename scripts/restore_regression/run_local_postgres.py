"""Run a fictional-only restore regression in a new loopback PostgreSQL 17 cluster.

No existing database, credentials file, archive or hosted service is consulted.
The checkout is imported read-only; generated files stay in an isolated work area.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def run(args, *, timeout=120, operational=False):
    output = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL} if operational else {'capture_output': True}
    return subprocess.run([str(value) for value in args], timeout=timeout,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **output)


def checkout_state(repository):
    try:
        head = run(['git', '-C', repository, 'rev-parse', '--verify', 'HEAD'], timeout=20)
        changes = run(['git', '--no-optional-locks', '-C', repository, 'status',
            '--porcelain', '--untracked-files=all'], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None, False
    commit = head.stdout.decode('ascii', 'replace').strip()
    if head.returncode or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
        return None, False
    return commit, changes.returncode == 0 and not changes.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--pg-bin', required=True, type=Path)
    parser.add_argument('--work-dir', type=Path,
        help='Existing parent for synthetic artifacts outside the checkout (default: system temporary directory).')
    args = parser.parse_args()
    repository = args.repository.resolve(strict=True)
    pg_bin = args.pg_bin.resolve(strict=True)
    require((repository / 'manage.py').is_file(), 'DJANGO_CHECKOUT_REQUIRED')
    # Clear inherited application, database, cloud and checkout overrides.
    for name in list(os.environ):
        upper_name = name.upper()
        if upper_name == 'DATABASE_URL' or upper_name.startswith(
            ('PG', 'POSTGRES_', 'DJANGO_', 'NEHEDROU_', 'AWS_', 'DEMO_', 'RENDER',
             'RESEND_', 'EMAIL_', 'MFA_', 'PUBLIC_ORIGIN', 'GIT_', 'AUTH_TRUSTED_PROXY',
             'DEFAULT_FROM_EMAIL')
        ):
            os.environ.pop(name, None)
    work_dir = (args.work_dir or Path(tempfile.gettempdir())).resolve(strict=True)
    require(work_dir.is_dir() and not work_dir.is_relative_to(repository), 'WORK_AREA_MUST_BE_OUTSIDE_CHECKOUT')
    for name in ('pg_dump', 'pg_restore', 'initdb', 'pg_ctl'):
        binary = pg_bin / (name + ('.exe' if os.name == 'nt' else ''))
        result = run([binary, '--version'], timeout=20)
        require(result.returncode == 0 and re.search(rb'\b17\.', result.stdout), 'POSTGRES_17_BINARIES_REQUIRED')
    head_before, clean_before = checkout_state(repository)
    root = Path(__file__).resolve().parent
    directory = Path(tempfile.mkdtemp(prefix='nehedrou-restore-regression-', dir=work_dir))
    identity = uuid.uuid4().hex[:16]
    cluster = directory / 'cluster'
    temporary = directory / 'temp'
    temporary.mkdir()
    os.environ['TEMP'] = os.environ['TMP'] = os.environ['TMPDIR'] = str(temporary)
    tempfile.tempdir = str(temporary)
    username = 'restore_reg_' + identity
    password = secrets.token_urlsafe(40)
    password_file = directory / 'initdb-password.tmp'
    ctl = pg_bin / ('pg_ctl.exe' if os.name == 'nt' else 'pg_ctl')
    started = False
    summary = None
    started_at = time.monotonic()
    try:
        descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='ascii') as handle:
            handle.write(password)
        result = run([pg_bin / ('initdb.exe' if os.name == 'nt' else 'initdb'), '-D', cluster,
            '--username=' + username, '--pwfile=' + str(password_file), '--auth=scram-sha-256',
            '--encoding=UTF8', '--locale=C'])
        require(result.returncode == 0, 'LOCAL_INITDB_FAILED')
        password_file.unlink()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
            with (cluster / 'postgresql.conf').open('a', encoding='utf-8') as output:
                output.write("\nlisten_addresses='127.0.0.1'\nport=" + str(port) +
                    "\nssl=off\nlog_statement='none'\nlog_min_error_statement='panic'\nlog_error_verbosity='terse'\n")
        started = True  # Also attempt a stop if startup reports a partial failure.
        # A file also avoids inherited PIPE handles on Windows, while retaining
        # fictional-only startup diagnostics when the sandbox refuses a process.
        with (directory / 'pg-control.log').open('ab') as control_log:
            result = subprocess.run([str(value) for value in [ctl, '-D', cluster, '-l',
                directory / 'postgres.log', '-w', '-t', '60', 'start']],
                stdout=control_log, stderr=subprocess.STDOUT, timeout=80,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        require(result.returncode == 0, 'LOCAL_POSTGRES_START_FAILED')
        import psycopg
        with psycopg.connect(host='127.0.0.1', port=port, user=username,
                password=password, dbname='postgres', connect_timeout=5) as connection:
            require(Path(connection.execute('SHOW data_directory').fetchone()[0]).resolve() == cluster.resolve(), 'LOCAL_CLUSTER_IDENTITY_MISMATCH')
            require(connection.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1', 'LOCAL_BIND_NOT_LOOPBACK')
            methods = connection.execute('SELECT auth_method FROM pg_hba_file_rules WHERE error IS NULL AND auth_method IS NOT NULL').fetchall()
            require(methods and {row[0] for row in methods} == {'scram-sha-256'}, 'LOCAL_AUTH_NOT_SCRAM_ONLY')
        os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_DEBUG='0',
            DJANGO_SECRET_KEY=secrets.token_urlsafe(64), DEMO_MODE='1', DEMO_EPHEMERAL='0',
            DEMO_SEED_ON_START='0', MFA_REQUIRED='1', EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
            PUBLIC_ORIGIN='https://fictional-restore.example.invalid', POSTGRES_HOST='127.0.0.1',
            POSTGRES_MIGRATION_HOST='127.0.0.1', POSTGRES_PORT=str(port), POSTGRES_DB='postgres',
            POSTGRES_USER=username, POSTGRES_PASSWORD=password, NEHEDROU_MEDIA_BACKEND='filesystem',
            NEHEDROU_MEDIA_ROOT=str(directory / 'inactive-media'), NEHEDROU_MEDIA_DURABLE='0',
            NEHEDROU_PG_BIN=str(pg_bin), NEHEDROU_RESTORE_REGRESSION_CLUSTER=str(cluster),
            NEHEDROU_RESTORE_REGRESSION_ROOT=str(directory), PYTHONDONTWRITEBYTECODE='1')
        from cryptography.fernet import Fernet
        os.environ['NEHEDROU_BACKUP_KEY'] = Fernet.generate_key().decode('ascii')
        sys.path[:0] = [str(root), str(repository)]
        import django
        django.setup()
        from django.db import connections
        # Preserve Django's populated TEST defaults (MIRROR, MIGRATE, ...).
        connections['default'].settings_dict['TEST']['NAME'] = 'restore_reg_source_' + identity
        from django.core.management import call_command
        call_command('test', 'postgres_roundtrip_tests', verbosity=2, interactive=False)
        summary = json.loads((directory / 'roundtrip-result.json').read_text(encoding='utf-8'))
    finally:
        password_file.unlink(missing_ok=True)
        if started:
            status = run([ctl, '-D', cluster, 'status'], timeout=20, operational=True)
            if status.returncode == 0:
                result = run([ctl, '-D', cluster, '-m', 'fast', '-w', 'stop'], timeout=60, operational=True)
                require(result.returncode == 0, 'LOCAL_POSTGRES_STOP_FAILED')
            else:
                require(status.returncode == 3, 'LOCAL_POSTGRES_STATUS_UNKNOWN')
    require(summary is not None, 'RESTORE_REGRESSION_DID_NOT_COMPLETE')
    head_after, clean_after = checkout_state(repository)
    exact_commit = bool(head_before and head_before == head_after and clean_before and clean_after)
    summary.update(local_cluster_stopped=True, only_new_loopback_scram_cluster=True,
        elapsed_seconds=round(time.monotonic() - started_at, 3),
        candidate_commit=head_before if exact_commit else None,
        checkout_head_before=head_before, checkout_head_after=head_after,
        clean_checkout_before=clean_before, clean_checkout_after=clean_after,
        remote_connections=False, fictional_only=True,
        scope='Local PostgreSQL 17/schema/fixture/media regression. No off-host copy, schedule, provider collation, RPO/RTO or clinical validation.')
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'summary': str(directory / 'summary.json'),
        'table_count': summary['table_count'], 'media_count': summary['media_count'],
        'postgres_major': 17, 'local_cluster_stopped': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never print subprocess output, environment or connection exceptions.
        code = str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z0-9_]+', str(error)) else None
        print(json.dumps({'status': 'failed', 'exception_type': type(error).__name__, 'code': code}))
        sys.exit(1)
