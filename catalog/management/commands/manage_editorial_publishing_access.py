"""Manage a single named publishing permission from the trusted operator CLI."""
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from catalog.publishing_access import change_publishing_access


class Command(BaseCommand):
    help = 'Preview or apply a publishing permission for an existing account and one spoken variety.'

    def add_arguments(self, parser):
        parser.add_argument('operation', choices=('grant', 'revoke'))
        parser.add_argument('--actor', required=True, help='Existing active superuser accountable for the operation.')
        parser.add_argument('--account', required=True, help='Existing recipient account username.')
        parser.add_argument('--variety', required=True, help='Exact existing spoken-variety code.')
        parser.add_argument('--apply', action='store_true', help='Apply the previewed permission change.')
        parser.add_argument('--expect-plan', help='The plan SHA-256 from the prior preview.')

    def handle(self, *args, **options):
        apply = options['apply']
        expected = options['expect_plan']
        if apply and not expected:
            raise CommandError('Applying requires --expect-plan from the preview.')
        if expected and not apply:
            raise CommandError('Use --expect-plan together with --apply.')
        try:
            result = change_publishing_access(
                actor_username=options['actor'], account_username=options['account'],
                variety_code=options['variety'], operation=options['operation'],
                expected_plan=expected if apply else None,
            )
        except (PermissionDenied, ValidationError) as error:
            if isinstance(error, ValidationError):
                raise CommandError(' '.join(error.messages)) from error
            raise CommandError(str(error)) from error
        except IntegrityError as error:
            raise CommandError('The permission could not be changed. Preview the plan again.') from error
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
