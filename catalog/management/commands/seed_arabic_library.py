"""Import versioned Arabic/Darja proposals without overwriting versions or approvals."""
import json
import uuid
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Activity, Variety


class Command(BaseCommand):
    help = 'Create unapproved Arabic and Algerian Darja drafts; optional isolated demonstration copies.'

    SOURCE_PACKS = ('arabic-library-v1.json', 'arabic-library-v2.json')

    def add_arguments(self, parser):
        parser.add_argument('--demo-copies', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['demo_copies'] and not settings.DEMO_MODE:
            raise CommandError('Demonstration copies require DEMO_MODE=1.')
        documents = [
            json.loads((Path(settings.BASE_DIR) / 'docs' / filename).read_text(encoding='utf-8'))
            for filename in self.SOURCE_PACKS
        ]
        varieties = {}
        for document in documents:
            for definition in document['varieties']:
                data = dict(definition)
                code = data.pop('code')
                variety, _ = Variety.objects.get_or_create(code=code, defaults=data)
                if variety.language != 'ar':
                    raise CommandError('Refusing a conflicting reserved Arabic variety.')
                varieties[code] = variety
        drafts = examples = 0
        for document in documents:
            for definition in document['activities']:
                row = dict(definition)
                code = row.pop('variety_code')
                series, version = row.pop('series'), row.pop('version')
                if code not in varieties or row.get('state') != 'draft' or row.get('is_demo') is not False or row.get('audio_a') or row.get('audio_b'):
                    raise CommandError('Arabic seeds require explicit unapproved drafts and no claimed clinical audio.')
                existing, fresh = Activity.objects.get_or_create(series=series, version=version, defaults=dict(row, variety=varieties[code]))
                if existing.is_demo or existing.variety_id != varieties[code].pk:
                    raise CommandError('Refusing a conflicting reserved draft series.')
                drafts += fresh
                if options['demo_copies']:
                    demo_series = uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + series)
                    existing, fresh = Activity.objects.get_or_create(series=demo_series, version=version, defaults=dict(row, variety=varieties[code], state='published', is_demo=True))
                    if not existing.is_demo or existing.variety_id != varieties[code].pk:
                        raise CommandError('Refusing a conflicting reserved demonstration series.')
                    examples += fresh
        self.stdout.write(f'{drafts} new Arabic/Darja drafts; {examples} new fictional demonstration copies. Existing versions, reviews and accounts preserved.')
