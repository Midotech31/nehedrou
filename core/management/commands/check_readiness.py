"""Technical launch gates. These checks never certify clinical effectiveness."""
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from catalog.models import Activity, Variety
from catalog.content_catalog import current_catalog
from catalog.integrity import integrity_scope, prepare_activities
from core.ops_readiness import smtp_configuration, email_configuration
from core.models import ProcessingActivity


DEFAULT_OFFERED_CONTENT_VARIETIES = ('fr-fr-pilot', 'en-us-general-pilot', 'ar-msa-pilot', 'ar-dz-pilot')


def offered_content_varieties():
    configured = getattr(settings, 'OFFERED_CONTENT_VARIETIES', DEFAULT_OFFERED_CONTENT_VARIETIES)
    if not isinstance(configured, (tuple, list)) or not configured or any(not isinstance(code, str) or not code or code != code.strip() for code in configured) or len(set(configured)) != len(configured):
        raise CommandError('OFFERED_CONTENT_VARIETIES must be a nonempty list or tuple of unique exact variety codes.')
    known = set(Variety.objects.filter(code__in=configured).values_list('code', flat=True))
    unknown = set(configured) - known
    if unknown:
        raise CommandError('Unknown offered content varieties: ' + ', '.join(repr(code) for code in sorted(unknown)))
    return tuple(configured)


class Command(BaseCommand):
    help = 'Report technical launch blockers without exposing accounts or credentials.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--strict', action='store_true', help='Fail if any technical gate is unmet.')

    def handle(self, *args, **options):
        offered = offered_content_varieties()
        # Show the editorial workload without treating drafts as clinically ready.
        # Count only the highest numbered version in each series, across states.
        latest_by_series = {}
        candidates = Activity.objects.filter(is_demo=False).select_related('variety').order_by('series', '-version', '-pk')
        for activity in candidates.iterator():
            latest_by_series.setdefault(activity.series, activity)
        pipeline_records = {code: [] for code in offered}
        for activity in latest_by_series.values():
            if activity.variety.code in pipeline_records:
                pipeline_records[activity.variety.code].append(activity)
        editorial_pipeline = {}
        for code, records in pipeline_records.items():
            states = Counter(activity.state for activity in records)
            editorial_pipeline[code] = {
                'latest_versions': len(records),
                'draft': states['draft'],
                'review': states['review'],
                'approved': states['approved'],
                'published': states['published'],
                'withdrawn': states['withdrawn'],
                'missing_one_or_more_audio_references': sum(not activity.audio_a.strip() or not activity.audio_b.strip() for activity in records),
            }
        published = Activity.objects.filter(state='published', is_demo=False).select_related('variety')
        current_ids = set(current_catalog(published).values_list('pk', flat=True))
        # Share byte checks only within this invocation, never with a later run.
        with integrity_scope():
            catalogue = prepare_activities(list(published))
            qualified = {a.pk: bool(a.usable and a.has_current_reviews()) for a in catalogue}
        languages = Counter(a.variety.language for a in catalogue)
        coverage = {code: languages[code] for code, _label in settings.LANGUAGES}
        published_varieties = Counter(a.variety.code for a in catalogue)
        available_varieties = Counter(a.variety.code for a in catalogue if a.pk in current_ids and qualified[a.pk])
        published_by_variety = {code: published_varieties[code] for code in offered}
        available_by_variety = {code: available_varieties[code] for code in offered}
        # Re-check deployment origin and durable media. Published versions are immutable.
        unavailable = sum(not qualified[a.pk] for a in catalogue)
        origin = urlsplit(settings.PUBLIC_ORIGIN)
        smtp = smtp_configuration()
        email = email_configuration(smtp=smtp)
        register = ProcessingActivity.objects.filter(organization__isnull=True, active=True)
        required_register_fields = ('controller_name', 'controller_contact', 'purposes', 'legal_basis',
                                    'data_subject_categories', 'personal_data_categories', 'recipient_categories',
                                    'international_transfers', 'retention_periods', 'security_measures', 'operations')
        def register_entry_populated(entry):
            fields = required_register_fields + (('data_protection_contact',) if entry.register_capacity == 'controller' else ())
            return all(bool((getattr(entry, field) or '').strip()) for field in fields)
        complete_register_count = sum(register_entry_populated(entry) for entry in register)
        checks = {
            'processing_register_present_and_populated': register.exists() and complete_register_count == register.count(),
            'demonstration_disabled': not settings.DEMO_MODE,
            'debug_disabled': not settings.DEBUG,
            'postgresql': connection.vendor == 'postgresql',
            'private_durable_media_configured': settings.MEDIA_STORAGE_DURABLE and not settings.DEMO_EPHEMERAL and (settings.MEDIA_STORAGE_BACKEND == 's3' or not Path(settings.MEDIA_ROOT).resolve().is_relative_to(Path(settings.BASE_DIR).resolve())),
            'privileged_mfa_required': settings.MFA_REQUIRED,
            'public_https_origin': origin.scheme == 'https' and bool(origin.netloc) and not origin.username and not origin.password,
            'email_configured': email['configured'],
            'current_available_nondemo_content_in_each_offered_variety': all(available_by_variety.values()),
            'published_audio_and_current_reviews_available': bool(catalogue) and unavailable == 0,
        }
        report = {
            'technical_gates_passed': all(checks.values()),
            'checks': checks,
            'processing_register': {
                'active_platform_records': register.count(),
                'active_by_capacity': {capacity: register.filter(register_capacity=capacity).count()
                                       for capacity, _label in ProcessingActivity._meta.get_field('register_capacity').choices},
                'populated_platform_records': complete_register_count,
                'scope': 'Only operator-entered platform records are counted. This completeness check does not assess legal accuracy or replace registers maintained by other controllers or processors.',
            },
            'smtp': smtp,
            'email': email,
            'published_nondemo_counts': coverage,
            'offered_content_varieties': list(offered),
            'published_nondemo_counts_by_variety': published_by_variety,
            'current_available_nondemo_counts_by_variety': available_by_variety,
            'editorial_pipeline_by_variety': editorial_pipeline,
            'editorial_pipeline_scope': 'Counts the highest-numbered non-demo version in each series regardless of editorial state. Missing audio counts blank A/B references only; it does not verify file integrity, variety, rights, review or availability.',
            'content_coverage_scope': 'Interface-language counts are descriptive only. Every explicitly offered spoken variety requires its own currently usable non-demo practice version, exact media, current reviews and authorised availability; MSA never covers Algerian Darja.',
            'versions_with_unavailable_audio_or_reviews': unavailable,
            'manual_gates_required': ['professional_content_and_audio_validation', 'native_language_review', 'browser_and_accessibility_acceptance', 'backup_restore_and_concurrency_acceptance', 'applicable_launch_obligations', 'processing_register_accuracy_and_legal_review', 'clinical_effectiveness_claims_require_separate_evidence'],
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
            for code, counts in editorial_pipeline.items():
                self.stdout.write('CONTENT ' + code + ': ' + json.dumps(counts, sort_keys=True))
            self.stdout.write(report['scope'])
        if options['strict'] and not report['technical_gates_passed']:
            raise CommandError('Technical launch gates are not met.')
