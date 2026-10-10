"""Hosted demonstration isolation and health regressions."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, override_settings


class DeploymentSettingsTests(SimpleTestCase):
    def test_start_script_initializes_from_outside_project(self):
        # Exercise the actual startup entry point, including migration and seeding.
        # Gunicorn itself is Linux-only; replace only the final process handoff.
        with tempfile.TemporaryDirectory() as directory:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('DJANGO_', 'POSTGRES_', 'DEMO_', 'RENDER')) and k not in ('MFA_REQUIRED', 'PUBLIC_ORIGIN', 'PYTHONPATH')}
            env.update(DJANGO_SECRET_KEY='test-only-' + 'x' * 60, DJANGO_DEBUG='0', DEMO_MODE='1', DEMO_EPHEMERAL='1', DEMO_DATABASE_PATH=str(Path(directory) / 'startup.sqlite3'), DEMO_PASSWORD='fictional-startup-only', MFA_REQUIRED='0', RENDER='true', RENDER_EXTERNAL_HOSTNAME='nehedrou-test.onrender.com')
            script = str(settings.BASE_DIR / 'scripts' / 'render_start.py')
            code = "import os,runpy;from unittest.mock import patch;\nwith patch('os.execvp') as handoff:\n runpy.run_path(" + repr(script) + ",run_name='__main__')\n assert handoff.call_count==1\n assert handoff.call_args.args[0]=='gunicorn'\nfrom django.contrib.auth import get_user_model\nassert get_user_model().objects.filter(username='famille').exists()\nprint('STARTUP_VERIFIED')"
            result = subprocess.run([sys.executable, '-c', code], cwd=directory, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('STARTUP_VERIFIED', result.stdout)

    def load_settings(self, **values):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DJANGO_', 'POSTGRES_', 'DEMO_', 'RENDER')) and k not in ('MFA_REQUIRED', 'PUBLIC_ORIGIN')}
        env.update(DJANGO_SECRET_KEY='test-only-' + 'x' * 60, DJANGO_DEBUG='0', DEMO_MODE='0')
        env.update(values)
        code = "import json;from config import settings as s;print(json.dumps({'debug':s.DEBUG,'demo':s.DEMO_MODE,'ephemeral':s.DEMO_EPHEMERAL,'engine':s.DATABASES['default']['ENGINE'],'hosts':s.ALLOWED_HOSTS,'origin':s.PUBLIC_ORIGIN,'secure':s.SESSION_COOKIE_SECURE,'proxy':getattr(s,'SECURE_PROXY_SSL_HEADER',None)}))"
        return subprocess.run([sys.executable, '-c', code], cwd=settings.BASE_DIR, env=env, text=True, capture_output=True)

    def test_clinical_mode_still_rejects_sqlite(self):
        self.assertNotEqual(self.load_settings().returncode, 0)
        self.assertNotEqual(self.load_settings(DEMO_EPHEMERAL='1').returncode, 0)

    def test_hosted_demo_can_use_temporary_storage_without_debug(self):
        result = self.load_settings(DEMO_MODE='1', DEMO_EPHEMERAL='1', RENDER='true', RENDER_EXTERNAL_HOSTNAME='nehedrou-test.onrender.com')
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertFalse(values['debug'])
        self.assertTrue(values['secure'])
        self.assertEqual(values['origin'], 'https://nehedrou-test.onrender.com')
        self.assertIn('nehedrou-test.onrender.com', values['hosts'])
        self.assertEqual(values['proxy'], ['HTTP_X_FORWARDED_PROTO', 'https'])
        self.assertEqual(values['engine'], 'django.db.backends.sqlite3')

    def test_render_rejects_debug_and_invalid_hostname(self):
        self.assertNotEqual(self.load_settings(DEMO_MODE='1', DEMO_EPHEMERAL='1', RENDER='true', DJANGO_DEBUG='1').returncode, 0)
        self.assertNotEqual(self.load_settings(DEMO_MODE='1', DEMO_EPHEMERAL='1', RENDER='true', RENDER_EXTERNAL_HOSTNAME='https://outside.example').returncode, 0)


class HostedRoutesTests(TestCase):
    def test_health_checks_database_and_is_not_cached(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.post('/healthz/').status_code, 405)

    def test_health_failure_does_not_expose_connection_details(self):
        with patch('core.health.connection.cursor', side_effect=DatabaseError('private-connection-marker')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})
        self.assertNotContains(response, 'private-connection-marker', status_code=503)

    @override_settings(DEMO_MODE=True, DEMO_EPHEMERAL=True)
    def test_temporary_test_warning_in_all_languages(self):
        for language, text in [('fr', 'Les modifications peuvent disparaître'), ('en', 'Changes may disappear'), ('ar', 'قد تختفي التغييرات')]:
            response = self.client.get('/' + language + '/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, text)
