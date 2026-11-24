"""CI-only Docker smoke: real Gunicorn + disposable PostgreSQL 17, no cloud.

Run after building the application image. Containers share an internal network;
no ports are published. HTTP is probed on loopback inside the application
container. All credentials/data are fictional. The SQLite smoke remains separate.
"""
import argparse
import base64
from email.message import Message
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid

POSTGRES_IMAGE = 'postgres:17-alpine'  # Same image family already used by CI.
MAX_BODY = 2 * 1024 * 1024

# Execute inside the application container. This tests its real HTTP listener
# without depending on platform-specific host access to an internal bridge.
HTTP_PROBE = '''
import base64,json,sys
from urllib.error import HTTPError,URLError
from urllib.request import HTTPRedirectHandler,ProxyHandler,Request,build_opener
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,message,headers,new_url):
        return None
opener=build_opener(ProxyHandler({}),NoRedirect())
request=Request('http://127.0.0.1:10000'+sys.argv[1],headers={'X-Forwarded-Proto':'https'})
try:
    try:
        response=opener.open(request,timeout=8)
    except HTTPError as error:
        response=error
    with response:
        body=response.read(2*1024*1024+1)
        print(json.dumps({'status':response.code,'content_type':response.headers.get('Content-Type',''),
            'cache_control':response.headers.get('Cache-Control',''),'body':base64.b64encode(body).decode('ascii')}))
except (OSError,URLError):
    print(json.dumps({'status':0,'content_type':'','cache_control':'','body':''}))
'''


class SmokeFailure(RuntimeError):
    pass


def require(ok, code):
    if not ok:
        raise SmokeFailure(code)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.language = self.direction = self.stylesheet = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'html':
            self.language, self.direction = attrs.get('lang'), attrs.get('dir')
        if tag == 'link' and attrs.get('rel') == 'stylesheet' and not self.stylesheet:
            self.stylesheet = attrs.get('href')


class Smoke:
    def __init__(self, image, docker_config):
        require(sys.platform.startswith('linux'), 'LINUX_CI_RUNNER_REQUIRED')
        require(re.fullmatch(r'[a-z0-9][a-z0-9./:_-]{0,199}', image) is not None,
                'INVALID_LOCAL_IMAGE_TAG')
        self.image = image
        self.deadline = time.monotonic() + 360
        self.stage = 'preflight'
        identity = uuid.uuid4().hex[:12]
        self.network = 'nehedrou-smoke-network-' + identity
        self.database = 'nehedrou-smoke-postgres-' + identity
        self.application = 'nehedrou-smoke-web-' + identity
        self.fixture_name = 'Fictional CI persistence ' + identity
        self.network_created = self.database_attempted = self.application_attempted = False
        # Empty Docker configuration avoids importing operator registry credentials
        # or remote contexts. The public Linux hosted runner uses its local socket.
        essentials = ('PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL')
        self.docker_env = {key: os.environ[key] for key in essentials if key in os.environ}
        self.docker_env['DOCKER_CONFIG'] = str(docker_config)

    def docker(self, *arguments, timeout=30):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'SMOKE_TOTAL_DEADLINE_EXCEEDED')
        try:
            result = subprocess.run(['docker', *arguments], env=self.docker_env,
                capture_output=True, text=True, timeout=min(timeout, remaining), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise SmokeFailure('DOCKER_UNAVAILABLE_OR_TIMED_OUT') from None
        require(result.returncode == 0, 'DOCKER_COMMAND_FAILED')
        return result.stdout.strip()

    def wait_database(self):
        until = min(self.deadline, time.monotonic() + 45)
        while time.monotonic() < until:
            try:
                self.docker('exec', self.database, 'pg_isready', '--host=127.0.0.1',
                    '--username=nehedrou_ci_runtime', '--dbname=nehedrou_ci_runtime', timeout=5)
                return
            except SmokeFailure:
                time.sleep(1)
        raise SmokeFailure('POSTGRES_NOT_READY')

    def start_application(self):
        self.application_attempted = True
        self.docker('run', '--detach', '--pull=never', '--name', self.application,
            '--network', self.network,
            '--env', 'RENDER=true', '--env', 'DJANGO_DEBUG=0',
            '--env', 'DJANGO_SETTINGS_MODULE=config.settings',
            '--env', 'DJANGO_SECRET_KEY=ci-only-disposable-key-with-more-than-fifty-characters-long',
            '--env', 'DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost',
            '--env', 'PUBLIC_ORIGIN=https://ci.example.invalid',
            '--env', 'DEMO_MODE=1', '--env', 'DEMO_EPHEMERAL=0',
            '--env', 'DEMO_SEED_ON_START=0', '--env', 'MFA_REQUIRED=1',
            '--env', 'EMAIL_BACKEND=core.email_backends.DisabledEmailBackend',
            '--env', 'POSTGRES_HOST=pg-runtime', '--env', 'POSTGRES_MIGRATION_HOST=pg-migrate',
            '--env', 'POSTGRES_PORT=5432', '--env', 'POSTGRES_DB=nehedrou_ci_runtime',
            '--env', 'POSTGRES_USER=nehedrou_ci_runtime',
            '--env', 'POSTGRES_PASSWORD=ci-only-disposable-postgres',
            '--env', 'NEHEDROU_MEDIA_BACKEND=filesystem',
            '--env', 'NEHEDROU_MEDIA_DURABLE=0',
            '--env', 'NEHEDROU_MEDIA_ROOT=/tmp/nehedrou-ci-runtime-media', self.image)
    def response(self, path):
        target = urlsplit(path)
        require(not target.scheme and not target.netloc and path.startswith('/') and
                not path.startswith('//'), 'NONLOCAL_HTTP_TARGET_REFUSED')
        output = self.docker('exec', self.application, 'python', '-c', HTTP_PROBE, path, timeout=12)
        try:
            result = json.loads(output)
            body = base64.b64decode(result['body'], validate=True)
            require(len(body) <= MAX_BODY, 'HTTP_BODY_LIMIT_EXCEEDED')
            headers = Message()
            headers['Content-Type'] = result['content_type']
            headers['Cache-Control'] = result['cache_control']
            return result['status'], headers, body
        except (KeyError, TypeError, ValueError):
            raise SmokeFailure('INVALID_HTTP_PROBE_RESULT') from None

    def wait_health(self, status, label, *, seconds):
        until = min(self.deadline, time.monotonic() + seconds)
        while time.monotonic() < until:
            try:
                code, headers, body = self.response('/healthz/')
                if (code == status and json.loads(body) == {'status': label}
                        and headers.get('Cache-Control') == 'no-store'):
                    return
            except ValueError:
                pass
            time.sleep(1)
        raise SmokeFailure('HTTP_HEALTH_EXPECTATION_NOT_MET')

    def application_python(self, code, *arguments):
        output = self.docker('exec', self.application, 'python', '-c', code, *arguments)
        try:
            return json.loads(output)
        except ValueError:
            raise SmokeFailure('INVALID_APPLICATION_CHECK_RESULT') from None

    def verify_runtime(self):
        result = self.application_python(
            "import json,os;from pathlib import Path;import django;django.setup();"
            "from django.conf import settings;from django.db import connection;"
            "from django.db.migrations.executor import MigrationExecutor;"
            "executor=MigrationExecutor(connection);"
            "cursor=connection.cursor();cursor.execute('SHOW server_version_num');"
            "major=int(cursor.fetchone()[0])//10000;cursor.close();"
            "cmd=Path('/proc/1/cmdline').read_bytes().replace(b'\\0',b' ');"
            "print(json.dumps({'uid':os.geteuid(),'gunicorn':b'gunicorn' in cmd and b'config.wsgi:application' in cmd,"
            "'postgres':connection.vendor=='postgresql','database':connection.settings_dict['NAME'],"
            "'server_major':major,"
            "'runtime_host':connection.settings_dict['HOST'],'migration_host':os.environ['POSTGRES_MIGRATION_HOST'],"
            "'migrations_current':not executor.migration_plan(executor.loader.graph.leaf_nodes()),"
            "'persistent_demo':settings.DEMO_MODE and not settings.DEMO_EPHEMERAL}))")
        require(result == {'uid': 10001, 'gunicorn': True, 'postgres': True,
            'server_major': 17,
            'runtime_host': 'pg-runtime', 'migration_host': 'pg-migrate',
            'database': 'nehedrou_ci_runtime', 'migrations_current': True, 'persistent_demo': True},
            'PRODUCTION_RUNTIME_CONTRACT_FAILED')

    def verify_locale_and_static(self):
        code, _headers, body = self.response('/ar/')
        require(code == 200, f'ARABIC_PAGE_HTTP_{code}')
        page = Page()
        page.feed(body.decode('utf-8'))
        require(page.language == 'ar' and page.direction == 'rtl', 'ARABIC_LOCALE_NOT_RENDERED')
        target = urlsplit(page.stylesheet or '')
        require(not target.scheme and not target.netloc and target.path.startswith('/static/') and
                '..' not in target.path.split('/'), 'LOCAL_STATIC_STYLESHEET_REQUIRED')
        code, headers, body = self.response(page.stylesheet)
        require(code == 200 and bool(body) and headers.get_content_type() == 'text/css',
                'PRODUCTION_STATIC_ASSET_NOT_OK')

    def create_fixture(self):
        result = self.application_python(
            "import json,sys;import django;django.setup();from core.models import Organization;"
            "obj=Organization.objects.create(name=sys.argv[1]);"
            "print(json.dumps({'id':str(obj.pk),'count':Organization.objects.filter(name=sys.argv[1]).count()}))",
            self.fixture_name)
        require(result.get('count') == 1 and re.fullmatch(r'[0-9a-f-]{36}', result.get('id', '')) is not None,
                'FICTIONAL_FIXTURE_NOT_CREATED')
        return result['id']

    def verify_fixture(self, fixture_id):
        result = self.application_python(
            "import json,sys;import django;django.setup();from core.models import Organization;"
            "print(json.dumps({'preserved':Organization.objects.filter(pk=sys.argv[1],name=sys.argv[2]).exists(),"
            "'count':Organization.objects.filter(name=sys.argv[2]).count()}))", fixture_id, self.fixture_name)
        require(result == {'preserved': True, 'count': 1}, 'FICTIONAL_FIXTURE_NOT_PRESERVED')

    def execute(self):
        self.stage = 'local_images_and_network'
        image_id = self.docker('image', 'inspect', '--format', '{{.Id}}', self.image)
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) is not None, 'LOCAL_APP_IMAGE_REQUIRED')
        self.docker('network', 'create', '--internal', self.network)
        self.network_created = True
        self.stage = 'isolated_postgres'
        self.database_attempted = True
        self.docker('run', '--detach', '--name', self.database, '--network', self.network,
            '--network-alias', 'pg-runtime', '--network-alias', 'pg-migrate',
            '--env', 'POSTGRES_DB=nehedrou_ci_runtime',
            '--env', 'POSTGRES_USER=nehedrou_ci_runtime',
            '--env', 'POSTGRES_PASSWORD=ci-only-disposable-postgres', POSTGRES_IMAGE, timeout=90)
        self.wait_database()
        self.stage = 'first_application_start'
        self.start_application()
        self.wait_health(200, 'ok', seconds=90)
        self.verify_runtime()
        self.verify_locale_and_static()
        fixture = self.create_fixture()
        self.stage = 'application_replacement'
        self.docker('rm', '--force', '--volumes', self.application)
        self.application_attempted = False
        self.start_application()
        self.wait_health(200, 'ok', seconds=90)
        self.verify_runtime()
        self.verify_locale_and_static()
        self.verify_fixture(fixture)
        self.stage = 'database_outage'
        self.docker('stop', '--time', '5', self.database, timeout=15)
        self.wait_health(503, 'unavailable', seconds=25)
        self.stage = 'database_recovery'
        self.docker('start', self.database)
        self.wait_database()
        self.wait_health(200, 'ok', seconds=45)
        self.verify_fixture(fixture)
        return {'status': 'passed', 'application_image': image_id, 'postgres_major': 17,
            'real_gunicorn_nonroot': True, 'current_migrations_applied': True,
            'arabic_rtl_and_static_http_ok': True, 'fixture_survived_application_replacement': True,
            'database_outage_http_503': True, 'database_recovery_http_200': True,
            'fixture_survived_database_restart': True,
            'scope': 'Disposable local Docker PostgreSQL and filesystem media configuration only. No S3, hosted deployment, real data, email, load benchmark or service-level guarantee.'}

    def cleanup(self):
        commands = []
        if self.application_attempted:
            commands.append(['rm', '--force', '--volumes', self.application])
        if self.database_attempted:
            commands.append(['rm', '--force', '--volumes', self.database])
        if self.network_created:
            commands.append(['network', 'rm', self.network])
        ok = True
        for command in commands:
            try:
                result = subprocess.run(['docker', *command], env=self.docker_env,
                    capture_output=True, timeout=10, check=False)
                ok = result.returncode == 0 and ok
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='nehedrou-ci:pull-request')
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        print(json.dumps({'status': 'failed', 'stage': 'preflight', 'code': 'LINUX_CI_RUNNER_REQUIRED'}))
        return 1
    with tempfile.TemporaryDirectory(prefix='nehedrou-ci-docker-') as docker_config:
        try:
            smoke = Smoke(args.image, Path(docker_config))
        except SmokeFailure as error:
            print(json.dumps({'status': 'failed', 'stage': 'preflight', 'code': str(error)}))
            return 1
        report = None
        failure = None
        try:
            report = smoke.execute()
        except Exception as error:
            failure = str(error) if isinstance(error, SmokeFailure) else type(error).__name__
        finally:
            cleanup_ok = smoke.cleanup()
        if failure is not None or not cleanup_ok:
            print(json.dumps({'status': 'failed', 'stage': smoke.stage,
                'code': failure or 'OWNED_RESOURCE_CLEANUP_FAILED', 'owned_resources_removed': cleanup_ok}))
            return 1
        report['owned_resources_removed'] = True
        print(json.dumps(report))
        return 0


if __name__ == '__main__':
    sys.exit(main())
