"""Startup safeguards for email transport without contacting a provider."""
import json
import os
from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase


class EmailSettingsTests(SimpleTestCase):
    def settings_process(self, **values):
        prefixes = ('EMAIL_', 'RESEND_', 'POSTGRES_', 'DJANGO_', 'DEMO_', 'RENDER',
                    'MFA_', 'NEHEDROU_', 'AWS_')
        env = {key: value for key, value in os.environ.items() if not key.startswith(prefixes) and key != 'PUBLIC_ORIGIN'}
        env.update(DJANGO_DEBUG='1', DEMO_MODE='1', DEMO_EPHEMERAL='1',
                   DJANGO_SECRET_KEY='fictional-startup-test-secret-never-for-deployment-1234567890')
        env.update(values)
        source = """import json
from config import settings as s
print(json.dumps({'backend': s.EMAIL_BACKEND, 'enabled': s.RESEND_ENABLED,
    'key_present': bool(s.RESEND_API_KEY), 'connect': s.EMAIL_HTTP_CONNECT_TIMEOUT,
    'read': s.EMAIL_HTTP_READ_TIMEOUT}))"""
        return subprocess.run([sys.executable, '-c', source], env=env,
                              cwd=Path(__file__).resolve().parents[1],
                              capture_output=True, text=True, timeout=20)

    def test_local_console_and_hosted_disabled_defaults(self):
        local = self.settings_process()
        self.assertEqual(local.returncode, 0, local.stderr)
        self.assertEqual(json.loads(local.stdout), {
            'backend': 'django.core.mail.backends.console.EmailBackend', 'enabled': False,
            'key_present': False, 'connect': 5.0, 'read': 10.0})
        hosted = self.settings_process(DJANGO_DEBUG='0')
        self.assertEqual(hosted.returncode, 0, hosted.stderr)
        self.assertEqual(json.loads(hosted.stdout)['backend'], 'core.email_backends.DisabledEmailBackend')

    def test_explicit_backend_is_preserved_and_key_does_not_activate_transport(self):
        for backend in ('django.core.mail.backends.smtp.EmailBackend', 'core.email_backends.ResendEmailBackend'):
            with self.subTest(backend=backend):
                result = self.settings_process(DJANGO_DEBUG='0', EMAIL_BACKEND=backend,
                                               RESEND_API_KEY='fictional-private-key')
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data['backend'], backend)
                self.assertFalse(data['enabled'])
                self.assertNotIn('fictional-private-key', result.stdout + result.stderr)

    def test_https_timeouts_are_bounded_and_errors_do_not_repeat_invalid_values(self):
        for setting in ('EMAIL_HTTP_CONNECT_TIMEOUT', 'EMAIL_HTTP_READ_TIMEOUT'):
            for value in ('0', '-1', 'nan', 'inf', '31', 'private-invalid-timeout-marker'):
                with self.subTest(setting=setting, value=value):
                    result = self.settings_process(**{setting: value})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(setting + ' must be between', result.stderr)
                    self.assertNotIn('private-invalid-timeout-marker', result.stdout + result.stderr)
        for connect, read in (('1', '1'), ('15', '30')):
            result = self.settings_process(EMAIL_HTTP_CONNECT_TIMEOUT=connect,
                                           EMAIL_HTTP_READ_TIMEOUT=read)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_https_opt_in_requires_exact_one(self):
        for flag, enabled in (('0', False), ('true', False), ('', False), ('1', True)):
            with self.subTest(flag=flag):
                result = self.settings_process(RESEND_ENABLED=flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['enabled'], enabled)

    def test_canonical_origin_rejects_credentials_controls_and_non_origin_parts(self):
        for origin in ('https://user:private-origin-marker@host.tld', 'https://host.tld/path',
                       'https://host.tld?private-origin-marker', 'https://host.tld/#fragment',
                       'https://host.tld?', 'https://host.tld#',
                       'javascript:private-origin-marker', 'https://host.tld:99999',
                       'https://host.tld:0', 'https://host.tld\\evil', 'https://host.tld\n'):
            with self.subTest(origin=origin):
                result = self.settings_process(PUBLIC_ORIGIN=origin)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('PUBLIC_ORIGIN must be a complete HTTP(S) origin', result.stderr)
                self.assertNotIn('private-origin-marker', result.stderr + result.stdout)
        for origin in ('http://127.0.0.1:8000', 'https://app.operator-domain.tld/', 'https://[::1]:8443'):
            result = self.settings_process(PUBLIC_ORIGIN=origin)
            self.assertEqual(result.returncode, 0, result.stderr)
