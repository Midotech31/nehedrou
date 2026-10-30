"""Exercise the shipped form enhancement without substituting its event handlers."""
from pathlib import Path
import shutil
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase


@skipUnless(shutil.which('node'), 'Node is required for the forms runtime regression')
class FormsRuntimeTests(SimpleTestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [shutil.which('node'), str(Path(settings.BASE_DIR) / 'core/tests_helpers/forms_runtime.js'), scenario],
            cwd=settings.BASE_DIR, capture_output=True, text=True, encoding='utf-8', timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('forms-runtime:' + scenario + ':ok', result.stdout)

    def test_language_forms_keep_native_submitter_and_default_activation(self):
        self.run_scenario('native-language')

    def test_password_controls_preserve_values_labels_submit_and_pagehide_reset(self):
        self.run_scenario('password-controls')
