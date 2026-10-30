"""Prepare exact, unapproved MSA guide revisions without rewriting any history."""
import copy
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Activity, Variety
from catalog.services import allowed, clone_version
from core.models import User
from core.services import audit


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class Command(BaseCommand):
    help = 'Dry-run by default: prepare new unapproved MSA guide versions; require --actor and explicit --apply to write.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Active editorial account username; edit permission on MSA is required.')
        parser.add_argument('--apply', action='store_true', help='Create new draft versions; never approve or publish.')

    @transaction.atomic
    def handle(self, *args, **options):
        actor = User.objects.filter(username=options['actor'], is_active=True).first()
        if not actor:
            raise CommandError('Choose an existing active editorial actor.')
        root = Path(settings.BASE_DIR)
        document = json.loads((root/'docs/arabic-library-v1.json').read_text(encoding='utf-8'))
        matrix = json.loads((root/'docs/msa-editorial-parity-20261030.json').read_text(encoding='utf-8'))
        prepared = {row['series']: row for row in document['activities'] if row['kind'] == 'phonological_contrast'}
        if len(prepared) != 10 or set(prepared) != {row['series'] for row in matrix['activities']}:
            raise CommandError('The prepared source and editorial parity matrix do not match.')
        variety = Variety.objects.select_for_update().filter(code='ar-msa-pilot', language='ar').first()
        if not variety:
            self.stdout.write('No existing MSA variety. No versions changed.')
            return
        if not allowed(actor, variety, 'edit'):
            raise CommandError('The actor needs editorial edit permission for this spoken variety.')
        created = eligible = current = manual = missing = 0
        for entry in matrix['activities']:
            source = prepared[entry['series']]
            latest = Activity.objects.select_for_update().filter(series=source['series']).order_by('-version').first()
            if not latest:
                missing += 1
                self.stdout.write(f"MISSING {source['series']}: no existing series; no version created.")
                continue
            if latest.is_demo or latest.variety_id != variety.pk or latest.kind != 'phonological_contrast':
                raise CommandError('Conflicting reserved MSA series; no revisions committed.')
            if latest.practice_guide == source['practice_guide']:
                current += 1
                continue
            actual = {field:getattr(latest, field) for field in matrix['stimulus_fields']}
            if digest(actual) != entry['stimulus_sha256'] or digest(latest.practice_guide) != entry['previous_guide_sha256']:
                manual += 1
                self.stdout.write(f"MANUAL {source['series']} v{latest.version}: editorial work differs; preserved.")
                continue
            eligible += 1
            if options['apply']:
                try:
                    activity = clone_version(actor, latest)
                    activity.practice_guide = copy.deepcopy(source['practice_guide'])
                    activity.save(update_fields=['practice_guide', 'search_text'])
                except (PermissionDenied, ValidationError) as error:
                    raise CommandError('Prepared revision refused; no revisions committed: ' + str(error)) from error
                audit(actor, 'catalog.guide_revision_prepared', activity)
                created += 1
                self.stdout.write(f"DRAFT {source['series']} v{activity.version}: human reviews pending.")
            else:
                self.stdout.write(f"WOULD_CREATE {source['series']} after v{latest.version}: unapproved draft only.")
        self.stdout.write(f"{'APPLY' if options['apply'] else 'DRY RUN'}: {eligible} eligible, {created} new drafts, {current} already current, {manual} manual review, {missing} missing. No approvals, publication or availability decisions created.")
