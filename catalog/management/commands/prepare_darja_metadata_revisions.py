"""Stage bundled Darja metadata corrections on unchanged draft baselines."""
import copy
import json
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from catalog.models import Activity, DraftWorkingCopy, Variety
from catalog.services import allowed, clone_version
from core.models import User
from core.services import audit
from qualification.models import digest_value


VARIETY_CODE = 'ar-dz-pilot'
SOURCE_FILES = ('arabic-library-v1.json', 'arabic-library-v2.json')
SOURCE_IDENTITY = {'variety_code', 'series', 'version', 'state'}
ACTIVITY_IDENTITY = {'id', 'variety', 'series', 'version', 'state', 'created_at', 'search_text'}
SCHEMA = 'nehedrou-darja-metadata-plan-v1'


def changed_fields(old, new, fields):
    # JSON booleans and numbers have distinct meanings even when Python compares them as equal.
    return sorted(field for field in fields if digest_value(old[field]) != digest_value(new[field]))


def load_sources():
    fields = {field.name for field in Activity._meta.concrete_fields if field.name not in ACTIVITY_IDENTITY}
    documents = []
    for version, filename in enumerate(SOURCE_FILES, 1):
        try:
            raw = Path(settings.BASE_DIR, 'docs', filename).read_text(encoding='utf-8')
            rows = [row for row in json.loads(raw)['activities'] if row.get('variety_code') == VARIETY_CODE]
            sources = {str(UUID(row['series'])): row for row in rows}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise CommandError(f'Invalid Darja source document: {filename}.') from error
        if len(rows) != 32 or len(sources) != len(rows):
            raise CommandError(f'Unexpected Darja source series in {filename}.')
        for row in rows:
            if (set(row) != fields | SOURCE_IDENTITY
                    or type(row['version']) is not int or row['version'] != version
                    or row['state'] != 'draft' or row['is_demo'] is not False
                    or row['audio_a'] != '' or row['audio_b'] != '' or row['media_manifest'] != {}
                    or not isinstance(row['item_metadata'], dict) or set(row['item_metadata']) != {'a', 'b'}):
                raise CommandError(f'Unexpected Darja source row shape or state in {filename}.')
        documents.append(sources)
    previous, updated = documents
    if previous.keys() != updated.keys():
        raise CommandError('The two Darja source documents do not contain the same series.')
    for series, replacement in updated.items():
        original = previous[series]
        if set(changed_fields(original, replacement, replacement)) != {'version', 'item_metadata'}:
            raise CommandError('The Darja correction must change only word metadata and source version.')
    return previous, updated, fields


def assess(queryset, variety, series, previous, updated, fields):
    latest = queryset.filter(series=series).order_by('-version').first()
    entry = {'series': series}
    if not latest:
        return {**entry, 'status': 'missing', 'reason': 'no_baseline'}, None
    if latest.is_demo or latest.variety_id != variety.pk:
        return {**entry, 'status': 'manual', 'reason': 'scope_mismatch'}, None

    entry.update(activity_id=str(latest.pk), version=latest.version, state=latest.state)
    authored = {field: getattr(latest, field) for field in fields}
    if latest.version >= updated['version'] and not changed_fields(authored, updated, fields):
        return {**entry, 'status': 'current', 'fingerprint': latest.fingerprint()}, latest
    if latest.state != 'draft' or latest.version != previous['version']:
        return {**entry, 'status': 'manual', 'reason': 'state_or_version_changed'}, None
    differences = changed_fields(authored, previous, fields)
    if differences:
        return {**entry, 'status': 'manual', 'reason': 'content_changed', 'changed_fields': differences}, None
    if latest.reviews.exists():
        return {**entry, 'status': 'manual', 'reason': 'recorded_review'}, None
    if DraftWorkingCopy.objects.filter(activity=latest, committed=False, dismissed=False).exists():
        return {**entry, 'status': 'manual', 'reason': 'open_working_copy'}, None
    return {**entry, 'status': 'eligible', 'fingerprint': latest.fingerprint()}, latest


class Command(BaseCommand):
    help = 'Plan selected Darja metadata revisions on exact draft baselines; with explicit apply, create drafts.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Existing active editorial account username.')
        parser.add_argument('--series', action='append', type=UUID, help='A bundled Darja series UUID. Repeat to select several.')
        parser.add_argument('--expect-plan', help='The plan SHA-256 from a prior preview of the same selection.')
        parser.add_argument('--apply', action='store_true', help='Apply the previewed plan to the selected draft series.')

    @transaction.atomic
    def handle(self, *args, **options):
        apply = options['apply']
        selected = options['series'] or []
        if apply and (not selected or not options['expect_plan']):
            raise CommandError('Applying requires explicit --series and --expect-plan from a preview.')
        if len(set(selected)) != len(selected):
            raise CommandError('Each Darja series may be selected only once.')
        previous, updated, fields = load_sources()
        series = sorted(str(identifier) for identifier in selected) if selected else sorted(updated)
        if set(series) - updated.keys():
            raise CommandError('Choose series from the bundled Darja correction.')

        variety_query = Variety.objects
        activities = Activity.objects
        if apply:
            # Use the same variety-before-activity locking order as clone_version.
            variety_query = variety_query.select_for_update()
            activities = activities.select_for_update()
        variety = variety_query.filter(code=VARIETY_CODE, language='ar').first()
        actor = User.objects.filter(username=options['actor'], is_active=True).first()
        if not variety or not actor or not allowed(actor, variety, 'edit'):
            raise CommandError('Choose an existing active editor for the Darja pilot variety.')

        targets = [assess(activities, variety, key, previous[key], updated[key], fields) for key in series]
        plan = {
            'schema': SCHEMA,
            'variety': VARIETY_CODE,
            'source_sha256': digest_value({'previous': previous, 'updated': updated}),
            'entries': [entry for entry, _ in targets],
        }
        plan_sha = digest_value(plan)
        created = []
        if apply:
            if options['expect_plan'] != plan_sha:
                raise CommandError('The plan changed. Preview the same selection again before applying.')
            if any(entry['status'] not in ('eligible', 'current') for entry, _ in targets):
                raise CommandError('Each selected draft must be eligible or already current. Review the plan.')
            for entry, latest in targets:
                if entry['status'] == 'current':
                    continue
                if DraftWorkingCopy.objects.filter(activity=latest, committed=False, dismissed=False).exists():
                    raise CommandError('A working copy was opened. Preview the selection again before applying.')
                replacement = updated[entry['series']]
                try:
                    draft = clone_version(actor, latest)
                    if draft.version != replacement['version']:
                        raise CommandError('The latest version changed. Preview the selection again before applying.')
                    draft.item_metadata = copy.deepcopy(replacement['item_metadata'])
                    draft.save(update_fields=['item_metadata', 'search_text'])
                except (IntegrityError, PermissionDenied, ValidationError) as error:
                    raise CommandError('The Darja revision could not be applied. Preview the selection again.') from error
                audit(actor, 'catalog.darja_metadata_revision_prepared', draft)
                created.append({'series': entry['series'], 'id': str(draft.pk), 'version': draft.version,
                                'fingerprint': draft.fingerprint()})
        self.stdout.write(json.dumps({**plan, 'plan_sha256': plan_sha, 'created': created},
                                     ensure_ascii=False, indent=2))
