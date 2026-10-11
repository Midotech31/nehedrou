import json
from django.core.management.base import BaseCommand, CommandError
from core.backups import create_backup

class Command(BaseCommand):
    help='Create an encrypted database and private media backup outside the checkout.'
    def add_arguments(self,parser):
        parser.add_argument('--destination',required=True)
        parser.add_argument('--quiescent',action='store_true',help='Confirm that application writes and media changes have been stopped for this backup.')
    def handle(self,*args,**options):
        if not options['quiescent']:raise CommandError('Stop application writes and media changes, then pass --quiescent. Schedule through a private operator job.')
        self.stdout.write(json.dumps(create_backup(options['destination'])))
