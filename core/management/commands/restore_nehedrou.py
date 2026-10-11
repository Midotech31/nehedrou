import json
from django.core.management.base import BaseCommand
from core.backups import inspect_backup, restore_backup

class Command(BaseCommand):
    help='Verify an encrypted backup or restore into a new isolated database and media directory.'
    def add_arguments(self,parser):
        parser.add_argument('--source',required=True)
        parser.add_argument('--verify-only',action='store_true')
        parser.add_argument('--media-destination')
        parser.add_argument('--sqlite-destination')
        parser.add_argument('--postgres-database')
    def handle(self,*args,**options):
        if options['verify_only']:
            manifest,entries=inspect_backup(options['source'])
            result={'verified':True,'database_engine':manifest['database_engine'],'file_count':len(entries)}
        else:
            from django.core.management.base import CommandError
            if not options['media_destination']:raise CommandError('Provide a fresh private media destination.')
            result=restore_backup(options['source'],options['media_destination'],options['sqlite_destination'],options['postgres_database'])
        self.stdout.write(json.dumps(result))
