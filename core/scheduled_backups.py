"""Opt-in private scheduler entry point. This module never installs a scheduler."""
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings
from django.core.management.base import CommandError
from core.backups import cipher, create_backup, inspect_backup, private_path


def hook_path(name):
    value = os.getenv(name, '')
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_file() or path.resolve().is_relative_to(Path(settings.BASE_DIR).resolve()):
        raise CommandError('Configure existing absolute private quiesce/resume hook executables outside the checkout.')
    return path.resolve()


def run_hook(path, label):
    try:
        result = subprocess.run([str(path)], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise CommandError(label + ' hook failed or timed out; inspect private operator logs.')
    if result.returncode:
        raise CommandError(label + ' hook failed; inspect private operator logs. Hook output is deliberately not printed.')


def scheduled_backup():
    if os.getenv('NEHEDROU_BACKUP_SCHEDULE_ENABLED') != '1':
        raise CommandError('Scheduled backups are disabled. Configure and review the private operator job first.')
    if os.getenv('NEHEDROU_BACKUP_OFFHOST_CONFIRMED') != '1':
        raise CommandError('Confirm the separately managed private off-host destination before enabling the job.')
    destination_dir = Path(os.getenv('NEHEDROU_BACKUP_DESTINATION', ''))
    if not destination_dir.is_absolute() or not destination_dir.is_dir():
        raise CommandError('Configure an existing absolute private off-host backup directory.')
    destination_dir = destination_dir.resolve()
    cipher()  # Verify key configuration before touching application availability.
    quiet = hook_path('NEHEDROU_BACKUP_QUIESCE_HOOK')
    resume = hook_path('NEHEDROU_BACKUP_RESUME_HOOK')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = private_path(destination_dir / ('nehedrou-' + stamp + '-' + uuid.uuid4().hex[:12] + '.encrypted'))
    lock = destination_dir / '.nehedrou-backup.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise CommandError('A backup lock already exists. Check the running or interrupted job privately before retrying.')
    os.close(descriptor)
    try:
        try:
            run_hook(quiet, 'Quiesce')
            result = create_backup(destination)
            manifest, _entries = inspect_backup(destination)
            result.update(authenticated_manifest_verified=True, schema=manifest['schema'])
        finally:
            # A partially successful quiesce hook can already have stopped writes.
            run_hook(resume, 'Resume')
    finally:
        lock.unlink()
    return result
