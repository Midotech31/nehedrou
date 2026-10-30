import json
from django.core.management.base import BaseCommand, CommandError
from core.ops_readiness import operations_report


class Command(BaseCommand):
    help = 'Report operational and SMTP configuration; opt in to database/storage reads. Never send email.'
    def add_arguments(self, parser):
        parser.add_argument('--database', action='store_true', help='Time a SELECT 1 against this explicitly configured environment.')
        parser.add_argument('--storage-object', help='Time a bounded read of one existing private sentinel object; its key is not printed.')
        parser.add_argument('--strict', action='store_true')
    def handle(self, *args, **options):
        report = operations_report(probe_database=options['database'], storage_object=options['storage_object'])
        self.stdout.write(json.dumps(report, ensure_ascii=True, indent=2))
        probes_ok = all(not report[name]['requested'] or report[name]['ok'] for name in ['database', 'storage'])
        if options['strict'] and (not report['configuration_ready'] or not probes_ok):
            raise CommandError('Operational checks are incomplete. No email was sent.')
