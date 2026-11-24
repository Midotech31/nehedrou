"""Guard the production template against an image built with local defaults."""
import json
import os
import runpy
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase


class ProductionStaticBuildTests(SimpleTestCase):
    def test_default_build_supplies_assets_for_production_arabic_home(self):
        environment = {
            key: value for key, value in os.environ.items() if key.upper() in {
                'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'TMPDIR',
            }
        }
        environment['DJANGO_SETTINGS_MODULE'] = 'config.settings'
        build_command = settings.BASE_DIR / 'scripts' / 'render_build.py'
        real_run = subprocess.run
        assets = (
            'brand/nehedrou-child-profile-header.png',
            'brand/nehedrou-child-profile-favicon.png',
            'brand/nehedrou-child-profile-touch.png',
            'product.css',
            'child-theme.css',
            'fonts/tajawal/Tajawal-Medium.ttf',
        )

        with tempfile.TemporaryDirectory() as directory:
            static_root = Path(directory) / 'static'
            initialize = textwrap.dedent("""
                import sys
                from pathlib import Path
                from django.conf import settings
                settings.STATIC_ROOT = Path(sys.argv[1])
                import django
                django.setup()
            """)
            collect = initialize + textwrap.dedent("""
                from django.core.management import call_command
                assert settings.DEBUG
                call_command('collectstatic', interactive=False, verbosity=0)
            """)

            def run_build_step(command, *, cwd, check, env=None):
                if command[1:] == ['manage.py', 'collectstatic', '--noinput']:
                    real_run(
                        [sys.executable, '-B', '-c', collect, str(static_root)],
                        cwd=cwd, env=env, check=check, capture_output=True, timeout=60,
                    )
                elif env is not None:
                    self.assertNotIn('NEHEDROU_BUILD_STATIC_MANIFEST', env)

            with patch.dict(os.environ, environment, clear=True), \
                    patch('subprocess.run', side_effect=run_build_step):
                runpy.run_path(str(build_command), run_name='__main__')
                self.assertNotIn('NEHEDROU_BUILD_STATIC_MANIFEST', os.environ)

            runtime_env = {
                **environment, 'DJANGO_DEBUG': '0', 'RENDER': 'true',
                'DEMO_MODE': '1', 'DEMO_EPHEMERAL': '1',
                'DEMO_DATABASE_PATH': str(Path(directory) / 'fixture.sqlite3'),
                'DJANGO_SECRET_KEY': 'fictional-static-ci-' + 'x' * 60,
                'PUBLIC_ORIGIN': 'https://testserver',
            }
            render = initialize + textwrap.dedent("""
                import json
                from django.contrib.staticfiles.storage import staticfiles_storage
                from django.test import Client

                client = Client()
                response = client.get('/ar/', secure=True)
                assert response.status_code == 200
                html = response.content.decode()
                assert 'lang="ar" dir="rtl"' in html
                for asset in json.loads(sys.argv[2]):
                    hashed_url = staticfiles_storage.url(asset)
                    assert hashed_url != settings.STATIC_URL + asset, asset
                    assert hashed_url in html, hashed_url
                    static_response = client.get(hashed_url, secure=True)
                    assert static_response.status_code == 200, hashed_url
            """)
            result = real_run(
                [sys.executable, '-B', '-c', render, str(static_root), json.dumps(assets)],
                cwd=settings.BASE_DIR, env=runtime_env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
