"""Technical launch gates. These checks never certify clinical effectiveness."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from catalog.models import Activity


class Command(BaseCommand):
    help = 'Report technical launch blockers without exposing accounts or credentials.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--strict', action='store_true', help='Fail if any technical gate is unmet.')

    def handle(self, *args, **options):
        catalogue = Activity.objects.filter(state='published', is_demo=False)
        coverage = {}
        for code, _label in settings.LANGUAGES:
            coverage[code] = catalogue.filter(variety__language=code).count()
        # Re-check deployment origin and durable media. Published versions are immutable.
        unavailable = sum(not (a.usable and a.has_current_reviews()) for a in catalogue)
        origin = urlsplit(settings.PUBLIC_ORIGIN)
        checks = {
            'demonstration_disabled': not settings.DEMO_MODE,
            'debug_disabled': not settings.DEBUG,
            'postgresql': connection.vendor == 'postgresql',
            'private_durable_media_configured': settings.MEDIA_STORAGE_DURABLE and not settings.DEMO_EPHEMERAL and (settings.MEDIA_STORAGE_BACKEND == 's3' or not Path(settings.MEDIA_ROOT).resolve().is_relative_to(Path(settings.BASE_DIR).resolve())),
            'privileged_mfa_required': settings.MFA_REQUIRED,
            'public_https_origin': origin.scheme == 'https' and bool(origin.netloc) and not origin.username and not origin.password,
            'smtp_configured': settings.EMAIL_BACKEND.endswith('smtp.EmailBackend') and bool(settings.EMAIL_HOST),
            'published_nondemo_content_in_each_offered_language': all(coverage.values()),
            'published_audio_and_current_reviews_available': bool(catalogue.exists()) and unavailable == 0,
        }
        report = {
            'technical_gates_passed': all(checks.values()),
            'checks': checks,
            'published_nondemo_counts': coverage,
            'versions_with_unavailable_audio_or_reviews': unavailable,
            'manual_gates_required': ['professional_content_and_audio_validation', 'native_language_review', 'browser_and_accessibility_acceptance', 'backup_restore_and_concurrency_acceptance', 'applicable_launch_obligations', 'clinical_effectiveness_claims_require_separate_evidence'],
            'storage_scope': 'Durability is operator-declared; verify persistence across restart, backup scheduling, off-host retention and restoration before launch.',
            'scope': 'A technical report, never clinical validation or commercial approval.',
        }
        from followup.models import ProbeDefinition
        from qualification.services import availability_for
        probes = ProbeDefinition.objects.filter(is_demo=False, organization__isnull=True)
        report['production_followup'] = {
            'original_drafts': probes.filter(state='draft').count(),
            'published_versions': probes.filter(state='published').count(),
            'available_versions': sum(p.ready and availability_for('production_followup', p.variety, p.fingerprint())['available'] for p in probes.filter(state='published')),
            'scope': 'Availability is specific to module, spoken variety and exact content SHA-256. Interface languages do not approve oral content.',
        }
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=True, indent=2))
        else:
            for name, passed in checks.items():
                self.stdout.write(('PASS ' if passed else 'BLOCK ') + name)
            self.stdout.write(report['scope'])
        if options['strict'] and not report['technical_gates_passed']:
            raise CommandError('Technical launch gates are not met.')
