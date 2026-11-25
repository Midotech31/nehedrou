"""Start Nehedrou's fictional demonstration on this computer."""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys


LOOPBACK = '127.0.0.1'
SYSTEM_KEYS = {
    'ALLUSERSPROFILE', 'APPDATA', 'COMSPEC', 'HOME', 'HOMEDRIVE', 'HOMEPATH',
    'LANG', 'LC_ALL', 'LC_CTYPE', 'LOCALAPPDATA', 'PATH', 'PATHEXT',
    'PROGRAMDATA', 'SYSTEMDRIVE', 'SYSTEMROOT', 'TEMP', 'TMP', 'TMPDIR',
    'USERPROFILE', 'WINDIR',
}


def system_environment():
    # Runtime children never inherit hosted application, mail or Python settings.
    return {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}


def state_path(workspace, name):
    path = workspace / name
    if not path.resolve().is_relative_to(workspace):
        raise SystemExit(f'Local demo path {name} must remain inside its workspace.')
    return path


def private_value(path, length):
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                       'w', encoding='utf-8') as handle:
            value = secrets.token_urlsafe(length)
            handle.write(value + '\n')
    except FileExistsError:
        value = path.read_text(encoding='utf-8').strip()
        if not value:
            raise SystemExit(f'Local demo configuration {path.name} is empty.')
    return value


def project_python(root, env, offline):
    relative = Path('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    venv = root / '.venv'
    python = venv / relative
    lock = root / 'requirements.lock'
    wheelhouse = root / 'wheelhouse'
    if not offline:
        if python.is_file():
            return python
        prepared = root.parent.parent / 'work' / 'venv' / relative
        if prepared.is_file():
            return prepared
    elif not wheelhouse.is_dir():
        raise SystemExit('The offline wheelhouse folder is missing.')

    if not python.is_file():
        subprocess.run([sys.executable, '-B', '-m', 'venv', str(venv)],
                       cwd=root, env=env, check=True)
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest()
    marker = venv / '.nehedrou-offline-lock'
    if not (offline and marker.is_file() and marker.read_text(encoding='ascii').strip() == lock_hash):
        command = [str(python), '-B', '-m', 'pip', 'install', '--require-hashes', '-r', str(lock)]
        install_env = env
        if offline:
            command += ['--no-index', '--no-cache-dir', '--disable-pip-version-check',
                        '--only-binary=:all:', '--find-links', str(wheelhouse)]
            install_env = {**env, 'PIP_CONFIG_FILE': os.devnull}
        subprocess.run(command, cwd=root, env=install_env, check=True)
        if offline:
            marker.write_text(lock_hash + '\n', encoding='ascii')
    return python


def run_demo(root, workspace, port, *, offline, prepare_only, isolated):
    workspace.mkdir(parents=True, exist_ok=True)
    password_file = state_path(workspace, '.demo-password')
    secret_file = state_path(workspace, '.demo-secret')
    database = state_path(workspace, 'demo.sqlite3')
    media = state_path(workspace, 'editorial_uploads')
    pitou_file = state_path(workspace, '.demo-password-pitou') if isolated else None
    origin = f'http://{LOOPBACK}:{port}'
    env = system_environment()
    python = project_python(root, env, offline)
    env.update(
        DJANGO_SETTINGS_MODULE='config.settings',
        DJANGO_DEBUG='1',
        DJANGO_SECRET_KEY=private_value(secret_file, 64),
        DJANGO_ALLOWED_HOSTS=f'{LOOPBACK},localhost',
        DEMO_MODE='1',
        DEMO_EPHEMERAL='0',
        DEMO_DATABASE_PATH=str(database),
        DEMO_PASSWORD=private_value(password_file, 24),
        NEHEDROU_MEDIA_BACKEND='filesystem',
        NEHEDROU_MEDIA_ROOT=str(media),
        EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
        PUBLIC_ORIGIN=origin,
    )
    commands = [['migrate', '--noinput'], ['seed_demo_roles'], ['seed_followup_demo']]
    if pitou_file is not None:
        env['DEMO_PASSWORD_PITOU'] = private_value(pitou_file, 24)
        commands.append(['seed_pitou_demo'])
    for command in commands:
        subprocess.run([str(python), '-B', 'manage.py', *command], cwd=root, env=env, check=True)

    print(f'Fictional demo passwords are stored in {password_file}', flush=True)
    if pitou_file is not None:
        print(f'The fictional Pitou password is stored in {pitou_file}', flush=True)
    if prepare_only:
        return
    print(f'Open Nehedrou at {origin}/fr/  /en/  /ar/', flush=True)
    print('Ctrl+C stops the local server.', flush=True)
    try:
        subprocess.run([str(python), '-B', 'manage.py', 'runserver', f'{LOOPBACK}:{port}', '--noreload'],
                       cwd=root, env=env, check=True)
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, help='Directory for this pilot’s local data and test access')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--offline', action='store_true', help='Install only from the adjacent wheelhouse')
    parser.add_argument('--prepare-only', action='store_true', help='Initialise the demonstration without serving it')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be from 1 to 65535')
    root = Path(__file__).resolve().parent
    workspace = args.workspace.expanduser().resolve() if args.workspace is not None else root
    run_demo(root, workspace, args.port, offline=args.offline, prepare_only=args.prepare_only,
             isolated=args.workspace is not None)


if __name__ == '__main__':
    main()
