import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from catalog.models import Activity, Variety

class Command(BaseCommand):
    help = 'Create 60 unapproved draft candidates, plus clearly marked demo copies when requested.'
    def add_arguments(self, parser):
        parser.add_argument('--demo-copies', action='store_true')
    @transaction.atomic
    def handle(self, *args, **options):
        rows = json.loads((Path(settings.BASE_DIR) / 'docs/catalog-candidates.json').read_text(encoding='utf-8'))
        created = 0
        for source in rows:
            row = dict(source)
            variety = Variety.objects.get(code=row.pop('variety_code'))
            series, version = row.pop('series'), row.pop('version')
            obj, fresh = Activity.objects.get_or_create(series=series, version=version, defaults=dict(row, variety=variety))
            created += fresh
            if options['demo_copies'] and settings.DEMO_MODE:
                import uuid
                demo_series = uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + str(series))
                demo = dict(row, variety=variety, is_demo=True, state='published')
                Activity.objects.get_or_create(series=demo_series, version=1, defaults=demo)
        self.stdout.write(f'{created} new drafts. Candidate content remains unapproved. Demo copies: {bool(options["demo_copies"] and settings.DEMO_MODE)}')
