"""Hosted demonstration isolation and health regressions."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.conf import settings
from django.db import DatabaseError, connection
from django.test import TestCase, SimpleTestCase, TransactionTestCase, override_settings


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

    def test_real_mode_requires_strict_readiness_before_gunicorn(self):
        import runpy
        from unittest.mock import patch
        with override_settings(DEBUG=False, DEMO_MODE=False, DEMO_EPHEMERAL=False), \
                patch.dict(os.environ, {'DEMO_SEED_ON_START':'0', 'POSTGRES_HOST':'runtime.fixture.invalid', 'POSTGRES_MIGRATION_HOST':'migration.fixture.invalid'}), \
                patch('subprocess.run') as command, patch('os.execvp') as handoff:
            runpy.run_path(str(settings.BASE_DIR/'scripts/render_start.py'), run_name='__main__')
        self.assertEqual(command.call_count, 2)
        self.assertEqual(command.call_args_list[0].kwargs['env']['POSTGRES_HOST'], 'migration.fixture.invalid')
        self.assertEqual(command.call_args.kwargs['env']['POSTGRES_HOST'], 'runtime.fixture.invalid')
        self.assertEqual(command.call_args.args[0][1:], ['manage.py', 'check_readiness', '--strict'])
        self.assertTrue(command.call_args.kwargs['check'])
        self.assertEqual(handoff.call_count, 1)

    def test_failed_real_mode_readiness_prevents_server_start(self):
        import runpy
        from subprocess import CalledProcessError
        from unittest.mock import patch
        failure = CalledProcessError(1, ['manage.py', 'check_readiness', '--strict'])
        with override_settings(DEBUG=False, DEMO_MODE=False, DEMO_EPHEMERAL=False), \
                patch.dict(os.environ, {'DEMO_SEED_ON_START':'0'}), \
                patch('subprocess.run', side_effect=[None, failure]), \
                patch('os.execvp') as handoff:
            with self.assertRaises(CalledProcessError):
                runpy.run_path(str(settings.BASE_DIR/'scripts/render_start.py'), run_name='__main__')
        handoff.assert_not_called()

    def test_disabled_demo_seeding_preserves_initialized_database(self):
        import runpy
        from unittest.mock import patch
        with override_settings(DEBUG=False,DEMO_MODE=True,DEMO_EPHEMERAL=False), patch.dict(os.environ,{'DEMO_SEED_ON_START':'0','POSTGRES_MIGRATION_HOST':'fictional-direct.example.test'}), patch('subprocess.run') as command, patch('os.execvp') as handoff:
            runpy.run_path(str(settings.BASE_DIR/'scripts/render_start.py'),run_name='__main__')
        self.assertEqual(command.call_count,1)
        self.assertEqual(command.call_args.args[0][1:4],['manage.py','migrate','--noinput'])
        self.assertEqual(command.call_args.kwargs['env']['POSTGRES_HOST'],'fictional-direct.example.test')
        self.assertEqual(handoff.call_count,1)

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
        self.assertEqual(values['options'], {'connect_timeout': 5})
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
            from core.auth_throttle import bucket_specs, reserve_attempt
            from django.urls import resolve
            from core.models import RateWindow
            assert connection.vendor=='sqlite'
            assert str(settings.DATABASES['default']['NAME']).endswith('rate-concurrency.sqlite3')
            with connection.schema_editor() as schema:
                schema.create_model(RateWindow)
            ip='203.0.113.17'
            specs=bucket_specs('login','concurrent-user',ip)
            key=next(key for key,limit,scope in specs if scope=='pair')
            window=RateWindow.objects.create(key=key)
            def post(attempting):
                connections.close_all()
                request=RequestFactory().post('/fr/login/',{'username':'concurrent-user'},REMOTE_ADDR=ip)
                request.user=AnonymousUser()
                request.resolver_match=resolve(request.path)
                attempting.set()
                try:
                    return 429 if reserve_attempt(request) else 204
                finally:
                    connections.close_all()
            result=[]
            for initial in [0,9]:
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
                assert window.count==min(10,initial+2),(initial,window.count)
                result.append({'initial':initial,'statuses':statuses,'count':window.count})
            assert RateWindow.objects.count()==3
            connections.close_all()
            print(json.dumps(result))
        ''')
        with tempfile.TemporaryDirectory() as directory:
            env = {k:v for k,v in os.environ.items() if not k.startswith(('DJANGO_','POSTGRES_','DEMO_','RENDER')) and k not in ('MFA_REQUIRED','PUBLIC_ORIGIN')}
            env.update(DJANGO_DEBUG='1',DEMO_MODE='1',DEMO_EPHEMERAL='1',DEMO_DATABASE_PATH=str(Path(directory)/'rate-concurrency.sqlite3'))
            result = subprocess.run([sys.executable,'-c',code],cwd=settings.BASE_DIR,env=env,text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),[{'initial':0,'statuses':[204,204],'count':2},{'initial':9,'statuses':[204,429],'count':10}])

    def test_render_rejects_debug_and_invalid_hostname(self):
        self.assertNotEqual(self.load_settings(DEMO_MODE='1', DEMO_EPHEMERAL='1', RENDER='true', DJANGO_DEBUG='1').returncode, 0)
        self.assertNotEqual(self.load_settings(DEMO_MODE='1', DEMO_EPHEMERAL='1', RENDER='true', RENDER_EXTERNAL_HOSTNAME='https://outside.example').returncode, 0)


@skipUnless(connection.vendor == 'postgresql' and os.getenv('NEHEDROU_STARTUP_PREFLIGHT_POSTGRES') == '1',
    'Requires an explicitly enabled disposable PostgreSQL startup fixture')
class RuntimeStartupPostgreSQLTests(TransactionTestCase):
    def test_real_startup_checks_runtime_database_after_direct_host_migration(self):
        config = connection.settings_dict
        # Evaluate the name after Django has created and selected its test DB.
        # Never run startup/migrations against an inherited application database.
        if config.get('HOST') not in ('localhost', '127.0.0.1') or not str(config.get('NAME', '')).startswith('test_'):
            self.skipTest('Requires a loopback PostgreSQL database named test_*')
        runtime_host = config['HOST']
        migration_host = 'localhost' if runtime_host == '127.0.0.1' else '127.0.0.1'
        with tempfile.TemporaryDirectory(prefix='nehedrou-runtime-startup-') as directory:
            # Keep only OS process essentials; no provider/storage/email secrets.
            essentials = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT'}
            env = {key:value for key,value in os.environ.items() if key.upper() in essentials}
            env.update(
                DJANGO_SECRET_KEY='disposable-startup-fixture-' + 'x' * 60,
                DJANGO_DEBUG='0', DEMO_MODE='0', DEMO_EPHEMERAL='0', DEMO_SEED_ON_START='0',
                RENDER='true', RENDER_EXTERNAL_HOSTNAME='nehedrou-startup-fixture.onrender.com',
                POSTGRES_HOST=runtime_host, POSTGRES_MIGRATION_HOST=migration_host,
                POSTGRES_PORT=str(config.get('PORT') or 5432), POSTGRES_DB=str(config['NAME']),
                POSTGRES_USER=str(config.get('USER') or ''), POSTGRES_PASSWORD=str(config.get('PASSWORD') or ''),
                NEHEDROU_MEDIA_ROOT=str(Path(directory) / 'media'), NEHEDROU_MEDIA_BACKEND='filesystem',
                NEHEDROU_MEDIA_DURABLE='0', MFA_REQUIRED='1', PUBLIC_ORIGIN='https://startup.example.invalid',
                EMAIL_BACKEND='core.email_backends.DisabledEmailBackend', PYTHONDONTWRITEBYTECODE='1',
                PYTHONIOENCODING='utf-8', TEMP=directory, TMP=directory)
            script = str(settings.BASE_DIR / 'scripts' / 'render_start.py')
            code = textwrap.dedent("""
                import os, runpy, subprocess, sys
                from unittest.mock import patch
                actual_run = subprocess.run
                observed = []
                def observe(command, **kwargs):
                    tail = command[1:]
                    if tail == ['manage.py', 'migrate', '--noinput']:
                        correct = kwargs['env']['POSTGRES_HOST'] == os.environ['POSTGRES_MIGRATION_HOST']
                        result = actual_run(command, **kwargs)
                        observed.append(('migration_completed', correct))
                        return result
                    if tail == ['manage.py', 'check_readiness', '--strict']:
                        correct = kwargs['env']['POSTGRES_HOST'] == os.environ['POSTGRES_HOST']
                        observed.append(('runtime_readiness_started', correct))
                        return actual_run(command, **kwargs)
                    raise AssertionError('Unexpected startup command')
                with patch('subprocess.run', side_effect=observe), patch('os.execvp') as handoff:
                    try:
                        runpy.run_path(sys.argv[1], run_name='__main__')
                    except subprocess.CalledProcessError as error:
                        assert error.cmd[1:] == ['manage.py', 'check_readiness', '--strict']
                        assert error.returncode != 0
                    else:
                        raise AssertionError('Incomplete real-mode fixture unexpectedly passed readiness')
                    handoff.assert_not_called()
                assert observed == [('migration_completed', True), ('runtime_readiness_started', True)]
                print('RUNTIME_POSTGRES_STARTUP_BLOCKED_AS_EXPECTED')
            """)
            result = subprocess.run([sys.executable, '-c', code, script], cwd=directory,
                env=env, text=True, capture_output=True, timeout=90)
        # Failure messages deliberately omit captured output and connection values.
        self.assertEqual(result.returncode, 0, 'Isolated real-mode startup contract failed')
        self.assertTrue('RUNTIME_POSTGRES_STARTUP_BLOCKED_AS_EXPECTED' in result.stdout,
            'Startup did not verify runtime routing and the absence of a server handoff')
        for key in ('processing_register_present_and_populated', 'current_available_nondemo_content_in_each_offered_variety'):
            self.assertTrue('BLOCK ' + key in result.stdout, 'The actual empty-fixture readiness checks did not run')


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
