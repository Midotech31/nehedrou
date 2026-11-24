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

try:
    port = int(os.getenv('PORT', '10000'))
except ValueError:
    raise SystemExit('Invalid listening port.') from None
if not 1 <= port <= 65535:
    raise SystemExit('Invalid listening port.')

runtime_env = dict(os.environ)
migration_env = runtime_env.copy()
migration_host = runtime_env.get('POSTGRES_MIGRATION_HOST')
if migration_host:
    from core.startup_database import verify_migration_database
    verify_migration_database(migration_host)
    migration_env['POSTGRES_HOST'] = migration_host
subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], check=True, env=migration_env)
if settings.DEMO_MODE and os.getenv('DEMO_SEED_ON_START', '1') == '1':
    subprocess.run([sys.executable, 'manage.py', 'seed_demo_roles'], check=True)
    subprocess.run([sys.executable, 'manage.py', 'seed_followup_demo'], check=True)
    if os.getenv('DEMO_PASSWORD_PITOU'):
        subprocess.run([sys.executable, 'manage.py', 'seed_pitou_demo'], check=True)
elif not settings.DEMO_MODE:
    # Do not start a real-data deployment until all technical readiness gates
    # pass against the migrated database and exact current content.
    subprocess.run([sys.executable, 'manage.py', 'check_readiness', '--strict'], check=True, env=runtime_env)

os.execvp('gunicorn', ['gunicorn', 'config.wsgi:application', '--bind', f'0.0.0.0:{port}', '--workers', '1', '--threads', '4', '--timeout', '60', '--access-logfile', '-', '--access-logformat', 'method=%(m)s status=%(s)s duration_s=%(L)s bytes=%(B)s', '--error-logfile', '-'])
