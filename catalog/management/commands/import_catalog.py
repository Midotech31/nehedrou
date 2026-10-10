import json
import uuid
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from catalog.models import Activity, Variety

class Command(BaseCommand):
    help = 'Validate and import a JSON list as draft content only.'
    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--apply', action='store_true')
    def handle(self, *args, **options):
        try:
            data = json.loads(Path(options['file']).read_text(encoding='utf-8'))
            if not isinstance(data, list):
                raise ValueError('Expected a list.')
            errors = []
            with transaction.atomic():
                for index, row in enumerate(data, 1):
                    try:
                        with transaction.atomic():
                            row = dict(row)
                            code = row.pop('variety_code')
                            if row.pop('state', 'draft') != 'draft':
                                raise ValueError('Imports must be drafts.')
                            row['variety'] = Variety.objects.get(code=code)
                            row['series'] = uuid.UUID(str(row.get('series', uuid.uuid4())))
                            Activity.objects.create(**row)
                    except (ValueError, TypeError, KeyError, ValidationError, Variety.DoesNotExist) as exc:
                        errors.append(f'Row {index}: {exc}')
                if errors or not options['apply']:
                    transaction.set_rollback(True)
            if errors:
                raise CommandError('\n'.join(errors))
            self.stdout.write(f'{len(data)} rows validated. ' + ('Imported as drafts.' if options['apply'] else 'Dry run: nothing saved.'))
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc))
