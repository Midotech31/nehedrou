"""Start the hosted test application; never embed or print its credentials."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
os.chdir(root)
# Running a script in scripts/ makes that directory Python's import root.
# Django's settings and apps live one level above it.
sys.path.insert(0, str(root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.conf import settings

if settings.DEBUG:
    raise SystemExit('The hosted server requires DJANGO_DEBUG=0.')
if settings.DEMO_EPHEMERAL and not settings.DEMO_MODE:
    raise SystemExit('Temporary storage requires fictional demonstration mode.')

subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], check=True)
if settings.DEMO_MODE:
    subprocess.run([sys.executable, 'manage.py', 'seed_demo'], check=True)
    subprocess.run([sys.executable, 'manage.py', 'seed_candidates', '--demo-copies'], check=True)

port = int(os.getenv('PORT', '10000'))
if not 1 <= port <= 65535:
    raise SystemExit('Invalid listening port.')
os.execvp('gunicorn', ['gunicorn', 'config.wsgi:application', '--bind', f'0.0.0.0:{port}', '--workers', '1', '--threads', '4', '--timeout', '60', '--access-logfile', '-', '--error-logfile', '-'])
