"""Explicit scoped import; the default only verifies files and reports a plan."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied, ValidationError
from core.models import User
from catalog.generated_pack import install_pack


class Command(BaseCommand):
    help = 'Verify the six generated French proposals; create unknown-rights media and new drafts only with --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Existing active editor username; no account is created.')
        parser.add_argument('--source-dir', required=True, help='Persistent directory containing the six exact full-resolution PNG sources.')
        parser.add_argument('--apply', action='store_true', help='Explicitly save private media and three new draft versions.')

    def handle(self, *args, **options):
        try:
            actor = User.objects.get(username=options['actor'])
            result = install_pack(actor, options['source_dir'], apply=options['apply'])
        except (User.DoesNotExist, OSError, ValueError, KeyError, PermissionDenied, ValidationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
