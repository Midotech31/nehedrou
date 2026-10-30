import json
from django.core.management.base import BaseCommand
from core.scheduled_backups import scheduled_backup


class Command(BaseCommand):
    help = 'Run an explicitly enabled private off-host encrypted backup job; never installs or enables a schedule.'
    def handle(self, *args, **options):
        self.stdout.write(json.dumps(scheduled_backup()))
