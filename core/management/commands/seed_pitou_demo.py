"""Explicit project-owner walkthrough, never a hidden or real superuser."""
import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Variety, EditorialGrant
from core.models import User, Organization, Membership
from .seed_demo import validate_demo_account
from .seed_demo_roles import ROLE_PRACTICE_ID, ROLE_PRACTICE_NAME


class Command(BaseCommand):
    help = 'Create the explicitly requested fictional Pitou cabinet and CMS access. Requires a separate private password.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Only allowed with DEMO_MODE=1.')
        password = os.getenv('DEMO_PASSWORD_PITOU', '')
        if len(password) < 20:
            raise CommandError('Set a separate DEMO_PASSWORD_PITOU of at least 20 characters.')
        if User.objects.filter(username__iexact='pitou').exclude(username='pitou').exists():
            raise CommandError('An ambiguous Pitou account already exists.')
        validate_demo_account('pitou')
        organization = Organization.objects.filter(pk=ROLE_PRACTICE_ID, name=ROLE_PRACTICE_NAME).first()
        if not organization or Membership.objects.filter(organization=organization).exclude(user__email__iendswith='@demo.example').exists():
            raise CommandError('Initialize the explicitly fictional role practice first.')
        user, created = User.objects.get_or_create(username='pitou', defaults={
            'email': 'pitou@demo.example', 'first_name': 'Pitou', 'is_staff': False, 'is_superuser': False})
        if created:
            user.set_password(password)
            user.save()
        Membership.objects.get_or_create(organization=organization, user=user, defaults={'role': 'clinician'})
        for variety in Variety.objects.filter(code__in=['fr-fr-pilot', 'en-us-general-pilot', 'ar-dz-pilot', 'ar-msa-pilot']):
            EditorialGrant.objects.get_or_create(user=user, variety=variety, defaults={'edit': True})
        self.stdout.write('Pitou fictional cabinet and CMS access ready. Existing passwords and recorded capabilities are preserved.')
