import json
from django.core.management.base import BaseCommand, CommandError
from core.erasure_checkpoint import capture, check


class Command(BaseCommand):
    help = 'Capture encrypted erasure references or compare an isolated restored database read-only. Never authorizes reopening.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True, help='Exact authenticated encrypted backup archive.')
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--capture', metavar='PRIVATE_PATH')
        mode.add_argument('--check', metavar='PRIVATE_PATH')
        parser.add_argument('--checkpoint-sha256', help='Independently retained ciphertext digest; required for --check.')
        parser.add_argument('--cutoff', required=True, help='Operator-required history cutoff, ISO8601 with UTC offset.')
        parser.add_argument('--expected-database', required=True, help='Independently verified configured DB name, or canonical absolute SQLite path.')
        parser.add_argument('--expected-host', help='Exact independently verified configured PostgreSQL host.')
        parser.add_argument('--expected-port', type=int, help='Exact independently verified configured PostgreSQL port.')

    def handle(self, *args, **options):
        if bool(options['capture']) == bool(options['check']):
            raise CommandError('ERASURE_CHECKPOINT_EXACTLY_ONE_MODE_REQUIRED')
        if options['capture']:
            if options['checkpoint_sha256']:
                raise CommandError('ERASURE_CHECKPOINT_DIGEST_IS_FOR_CHECK_ONLY')
            report = capture(options['archive'], options['capture'], options['cutoff'],
                options['expected_database'], options['expected_host'], options['expected_port'])
        else:
            if not options['checkpoint_sha256']:
                raise CommandError('ERASURE_CHECKPOINT_EXPECTED_DIGEST_REQUIRED')
            report = check(options['archive'], options['check'], options['checkpoint_sha256'], options['cutoff'],
                options['expected_database'], options['expected_host'], options['expected_port'])
        self.stdout.write(json.dumps(report, sort_keys=True))
        if report.get('blocking'):
            raise CommandError('ERASURE_CHECKPOINT_RECONCILIATION_BLOCKED')
