"""Start the local fictional demonstration. Run: python start.py"""
import os
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
os.chdir(root)
windows = os.name == 'nt'
relative = Path('Scripts/python.exe' if windows else 'bin/python')
python = root / '.venv' / relative
prepared = root.parents[1] / 'work' / 'venv' / relative
if not python.exists():
    if prepared.exists():
        python = prepared
    else:
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], check=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '--require-hashes', '-r', 'requirements.lock'], check=True)
env = os.environ.copy()
env.update(DJANGO_DEBUG='1', DEMO_MODE='1')
password_file = root / '.demo-password'
if not env.get('DEMO_PASSWORD'):
    if password_file.exists():
        env['DEMO_PASSWORD'] = password_file.read_text().strip()
    else:
        env['DEMO_PASSWORD'] = secrets.token_urlsafe(24)
        password_file.write_text(env['DEMO_PASSWORD'])
        try:
            password_file.chmod(0o600)
        except OSError:
            pass
for command in [['migrate', '--noinput'], ['seed_demo_roles'], ['seed_followup_demo']]:
    subprocess.run([str(python), 'manage.py', *command], env=env, check=True)
print('\nNehdrou: http://127.0.0.1:8000/fr/', flush=True)
print('Demo roles: responsable, orthophoniste, accompagnant, editeur, relecteur_clinique, relecteur_linguistique, gestionnaire', flush=True)
print('Historical accounts: praticien, famille, autre_praticien, editorial', flush=True)
print('Local demo password:', env['DEMO_PASSWORD'], flush=True)
print('Existing passwords are never reset. Ctrl+C stops the server.', flush=True)
try:
    subprocess.run([str(python), 'manage.py', 'runserver', '127.0.0.1:8000', '--noreload'], env=env, check=True)
except KeyboardInterrupt:
    pass
