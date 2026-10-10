import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from catalog.models import Variety
from followup.imports import import_definitions

class Command(BaseCommand):
    help = 'Validate conception-1 protocol examples; optional --apply creates unapproved original drafts only.'

    def add_arguments(self, parser):
        parser.add_argument('file', nargs='?', default=str(Path(__file__).resolve().parents[2] / 'data' / 'probes_draft.json'))
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            data = json.loads(Path(options['file']).read_text(encoding='utf-8-sig'))
            with transaction.atomic():
                rows = import_definitions(data)
                count = sum(created for _, created in rows)
                if not options['apply']:
                    transaction.set_rollback(True)
            self.stdout.write(f'{len(rows)} draft definitions verified, {count} new. ' + ('Drafts saved; no approvals supplied.' if options['apply'] else 'Dry run: nothing saved.'))
        except (OSError, ValueError, KeyError, TypeError, ValidationError, Variety.DoesNotExist) as error:
            raise CommandError(str(error))
