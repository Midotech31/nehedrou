import json
import uuid
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Activity, Variety


class Command(BaseCommand):
    help = 'Create versioned unapproved candidates; optional isolated demonstration copies.'

    def add_arguments(self, parser):
        parser.add_argument('--demo-copies', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        rows = json.loads((Path(settings.BASE_DIR) / 'docs/catalog-candidates.json').read_text(encoding='utf-8'))
        created = demos = 0
        for source in rows:
            row = dict(source)
            if row.get('state') != 'draft' or row.get('is_demo') is not False or row.get('audio_a') or row.get('audio_b'):
                raise CommandError('Candidate seeds must be unapproved drafts without claimed clinical audio.')
            variety = Variety.objects.get(code=row.pop('variety_code'))
            series, version = row.pop('series'), row.pop('version')
            _obj, fresh = Activity.objects.get_or_create(series=series, version=version, defaults=dict(row, variety=variety))
            created += fresh
            if options['demo_copies'] and settings.DEMO_MODE:
                demo_series = uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + str(series))
                demo = dict(row, variety=variety, is_demo=True, state='published')
                _example, fresh_demo = Activity.objects.get_or_create(series=demo_series, version=version, defaults=demo)
                demos += fresh_demo
        self.stdout.write(f'{created} new drafts; {demos} new demonstration versions. Existing content and reviews were not changed. No candidate is clinically approved.')
