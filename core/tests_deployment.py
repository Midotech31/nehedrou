"""Hosted demonstration isolation and health regressions."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
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
        code = "import json;from config import settings as s;print(json.dumps({'debug':s.DEBUG,'demo':s.DEMO_MODE,'ephemeral':s.DEMO_EPHEMERAL,'engine':s.DATABASES['default']['ENGINE'],'options':s.DATABASES['default'].get('OPTIONS',{}),'connection_age':s.DATABASES['default'].get('CONN_MAX_AGE'),'hosts':s.ALLOWED_HOSTS,'origin':s.PUBLIC_ORIGIN,'secure':s.SESSION_COOKIE_SECURE,'proxy':getattr(s,'SECURE_PROXY_SSL_HEADER',None)}))"
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
        self.assertEqual(values['options'], {'timeout':20,'transaction_mode':'IMMEDIATE'})

    def test_postgresql_keeps_its_production_configuration(self):
        # Settings import only: never connect to this fictional host.
        result = self.load_settings(POSTGRES_HOST='fictional-database.invalid',POSTGRES_PASSWORD='fictional-test-only')
        self.assertEqual(result.returncode,0,result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values['engine'],'django.db.backends.postgresql')
        self.assertEqual(values['options'],{})
        self.assertEqual(values['connection_age'],60)
        self.assertFalse(values['demo'])

    def test_file_sqlite_rate_limiter_serializes_concurrent_posts_and_preserves_limit(self):
        # This subprocess uses an actual private SQLite file and independent
        # connections, outside TestCase atomics and shared in-memory databases.
        code = textwrap.dedent('''
            import hashlib,json,os,time
            from concurrent.futures import ThreadPoolExecutor
            from threading import Event
            os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
            import django
            django.setup()
            from django.conf import settings
            from django.contrib.auth.models import AnonymousUser
            from django.db import connection,connections,transaction
            from django.http import HttpResponse
            from django.test import RequestFactory
            from core.middleware import AccessMiddleware
            from core.models import RateWindow
            assert connection.vendor=='sqlite'
            assert str(settings.DATABASES['default']['NAME']).endswith('rate-concurrency.sqlite3')
            with connection.schema_editor() as schema:
                schema.create_model(RateWindow)
            ip='203.0.113.17'
            key=hashlib.sha256(ip.encode()).hexdigest()
            window=RateWindow.objects.create(key=key)
            def post(attempting):
                connections.close_all()
                request=RequestFactory().post('/fr/login/',REMOTE_ADDR=ip)
                request.user=AnonymousUser()
                middleware=AccessMiddleware(lambda request:HttpResponse(status=204))
                attempting.set()
                try:
                    return middleware(request).status_code
                finally:
                    connections.close_all()
            result=[]
            for initial in [0,14]:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    with transaction.atomic():
                        # Hold a real write reservation while both POSTs begin.
                        # DEFERRED readers could otherwise fail their upgrade
                        # here immediately, even with the configured timeout.
                        RateWindow.objects.filter(pk=window.pk).update(count=initial)
                        events=[Event(),Event()]
                        futures=[pool.submit(post,event) for event in events]
                        assert all(event.wait(5) for event in events)
                        time.sleep(0.15)
                    statuses=sorted(f.result(timeout=25) for f in futures)
                window.refresh_from_db()
                expected=[204,204] if initial==0 else [204,429]
                assert statuses==expected,(initial,statuses)
                assert window.count==initial+2,(initial,window.count)
                result.append({'initial':initial,'statuses':statuses,'count':window.count})
            assert RateWindow.objects.count()==1
            connections.close_all()
            print(json.dumps(result))
        ''')
        with tempfile.TemporaryDirectory() as directory:
            env = {k:v for k,v in os.environ.items() if not k.startswith(('DJANGO_','POSTGRES_','DEMO_','RENDER')) and k not in ('MFA_REQUIRED','PUBLIC_ORIGIN')}
            env.update(DJANGO_DEBUG='1',DEMO_MODE='1',DEMO_EPHEMERAL='1',DEMO_DATABASE_PATH=str(Path(directory)/'rate-concurrency.sqlite3'))
            result = subprocess.run([sys.executable,'-c',code],cwd=settings.BASE_DIR,env=env,text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),[{'initial':0,'statuses':[204,204],'count':2},{'initial':14,'statuses':[204,429],'count':16}])

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
