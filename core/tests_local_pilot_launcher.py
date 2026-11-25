"""The local pilot launcher must discard the host's application settings."""
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

import start


class LocalPilotLauncherTests(SimpleTestCase):
    host_settings = {
        'POSTGRES_HOST': 'fictional-host.invalid',
        'POSTGRES_MIGRATION_HOST': 'fictional-migration-host.invalid',
        'DATABASE_URL': 'fictional-host-setting',
        'NEHEDROU_MEDIA_BACKEND': 's3',
        'NEHEDROU_MEDIA_ROOT': 'fictional-remote-location',
        'AWS_SECRET_ACCESS_KEY': 'fictional-s3-credential',
        'EMAIL_BACKEND': 'core.email_backends.ResendEmailBackend',
        'RESEND_API_KEY': 'fictional-mail-key',
        'RENDER': 'true',
        'DJANGO_SETTINGS_MODULE': 'fictional.hosted_settings',
        'DJANGO_SECRET_KEY': 'fictional-external-signing-key',
        'DEMO_PASSWORD': 'fictional-shared-host-password',
        'DEMO_PASSWORD_PITOU': 'fictional-host-pitou-password',
        'PUBLIC_ORIGIN': 'https://fictional-host.invalid',
        'PYTHONPATH': 'fictional-outside-module-directory',
    }

    def test_every_management_command_uses_only_the_selected_local_workspace(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / 'fictional-pilot'
            output = StringIO()
            with (
                patch.dict(os.environ, self.host_settings),
                patch.object(start, 'project_python', return_value=Path(sys.executable)),
                patch.object(start.subprocess, 'run') as command,
                redirect_stdout(output),
            ):
                start.run_demo(root, workspace, 8765, offline=True, prepare_only=False, isolated=True)

            commands = [call.args[0][3:] for call in command.call_args_list]
            self.assertEqual(commands, [
                ['migrate', '--noinput'], ['seed_demo_roles'], ['seed_followup_demo'],
                ['seed_pitou_demo'], ['runserver', '127.0.0.1:8765', '--noreload'],
            ])
            for call in command.call_args_list:
                env = call.kwargs['env']
                self.assertTrue(set(self.host_settings.values()).isdisjoint(env.values()))
                self.assertEqual(env['DJANGO_SETTINGS_MODULE'], 'config.settings')
                self.assertEqual(env['DEMO_DATABASE_PATH'], str(workspace / 'demo.sqlite3'))
                self.assertEqual(env['NEHEDROU_MEDIA_ROOT'], str(workspace / 'editorial_uploads'))
                self.assertEqual(env['NEHEDROU_MEDIA_BACKEND'], 'filesystem')
                self.assertEqual(env['EMAIL_BACKEND'], 'core.email_backends.DisabledEmailBackend')
                self.assertEqual(env['PUBLIC_ORIGIN'], 'http://127.0.0.1:8765')
                self.assertEqual(env['DEMO_EPHEMERAL'], '0')
                self.assertEqual(call.kwargs['cwd'], root)

            same_values = {name: (workspace / name).read_text().strip()
                           for name in ('.demo-password', '.demo-password-pitou', '.demo-secret')}
            self.assertEqual(len(set(same_values.values())), 3)
            self.assertTrue(all(value not in output.getvalue() for value in same_values.values()))
            with (
                patch.object(start, 'project_python', return_value=Path(sys.executable)),
                patch.object(start.subprocess, 'run') as prepare,
                redirect_stdout(StringIO()),
            ):
                start.run_demo(root, workspace, 8765, offline=True, prepare_only=True, isolated=True)
            self.assertEqual(prepare.call_count, 4)
            self.assertEqual(same_values, {name: (workspace / name).read_text().strip() for name in same_values})

    def test_offline_provisioning_never_uses_a_package_index(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            relative = Path('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            python = root / '.venv' / relative
            python.parent.mkdir(parents=True)
            python.touch()
            (root / 'wheelhouse').mkdir()
            (root / 'requirements.lock').write_text('locked fixture\n', encoding='ascii')
            with patch.object(start.subprocess, 'run') as command:
                self.assertEqual(start.project_python(root, {}, offline=True), python)
                self.assertEqual(start.project_python(root, {}, offline=True), python)
            command.assert_called_once()
            args = command.call_args.args[0]
            self.assertIn('--no-index', args)
            self.assertIn('--require-hashes', args)
            self.assertIn(str(root / 'wheelhouse'), args)
            self.assertEqual(command.call_args.kwargs['env']['PIP_CONFIG_FILE'], os.devnull)
