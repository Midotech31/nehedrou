"""Create explicit, separate fictional role profiles without resetting accounts."""
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from care.models import Child, FamilyLink, Program, ProgramItem
from catalog.content_catalog import current_catalog
from catalog.models import Activity, EditorialGrant, Variety
from core.models import Entitlement, Membership, Organization, User
from .seed_demo import DEMO_VARIETY_CODES, demo_password, validate_demo_account


ROLE_USERNAMES = ('responsable', 'orthophoniste', 'accompagnant', 'editeur',
                  'relecteur_clinique', 'relecteur_linguistique', 'gestionnaire')
ROLE_PASSWORD_ENV = {name: 'DEMO_PASSWORD_' + name.upper() for name in ROLE_USERNAMES}
ROLE_PRACTICE_ID = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-demo-role-practice')
ROLE_PRACTICE_NAME = 'Cabinet Parcours des rôles · fictif'
ROLE_CHILD_IDS = {name: uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-demo-role-child:' + name)
                  for name in ['responsable', 'orthophoniste']}
EDITORIAL_CAPABILITIES = {
    'editeur': {'edit': True, 'publish': True},
    'relecteur_clinique': {'clinical_review': True},
    'relecteur_linguistique': {'linguistic_review': True},
}


class Command(BaseCommand):
    help = 'Create fictional role accounts and a separate practice. Existing credentials and affiliations are preserved.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Only allowed with DEMO_MODE=1.')
        # Validate the whole request before the legacy initializer can write.
        passwords = {}
        for name in ROLE_USERNAMES:
            validate_demo_account(name)
            passwords[name] = demo_password(ROLE_PASSWORD_ENV[name])
        if Organization.objects.filter(name=ROLE_PRACTICE_NAME).exclude(pk=ROLE_PRACTICE_ID).exists():
            raise CommandError('The fictional role practice name is already in use.')
        existing = Organization.objects.filter(pk=ROLE_PRACTICE_ID).first()
        if existing and (existing.name != ROLE_PRACTICE_NAME
                         or Membership.objects.filter(organization=existing).exclude(user__email__iendswith='@demo.example').exists()
                         or Child.objects.filter(organization=existing).exclude(code__endswith='· fictif').exists()):
            raise CommandError('Refusing to reuse a practice without fictitious affiliation.')

        call_command('seed_demo', stdout=self.stdout, verbosity=options['verbosity'])
        call_command('seed_candidates', demo_copies=True, stdout=self.stdout, verbosity=options['verbosity'])
        accounts = {}
        new_accounts = set()
        for name in ROLE_USERNAMES:
            account, created = User.objects.get_or_create(
                username=name, defaults={'email': name + '@demo.example', 'is_staff': False, 'is_superuser': False})
            if created:
                new_accounts.add(name)
                account.set_password(passwords[name])
                account.save()
            accounts[name] = account

        organization, _ = Organization.objects.get_or_create(
            pk=ROLE_PRACTICE_ID, defaults={'name': ROLE_PRACTICE_NAME})
        Entitlement.objects.get_or_create(organization=organization, defaults={
            'plan': 'Fictional role walkthrough', 'child_quota': 15, 'practitioner_quota': 5,
            'expires_at': timezone.now() + timedelta(days=30)})
        for name, role in [('responsable', 'owner'), ('orthophoniste', 'clinician')]:
            Membership.objects.get_or_create(organization=organization, user=accounts[name], defaults={'role': role})

        varieties = list(Variety.objects.filter(code__in=DEMO_VARIETY_CODES).order_by('code'))
        examples = {}
        for variety in varieties:
            activity = current_catalog(Activity.objects.filter(variety=variety, is_demo=True, state='published', version__gte=2)).exclude(
                practice_guide={}).order_by('series', '-version').first()
            examples[variety.pk] = activity
        for name, code in [('responsable', 'Maya · fictif'), ('orthophoniste', 'Sami · fictif')]:
            child = Child.objects.filter(pk=ROLE_CHILD_IDS[name]).first()
            if child is None:
                child = Child.objects.filter(organization=organization, code=code).first()
            child_created = child is None
            if child_created:
                if any(activity is None for activity in examples.values()):
                    raise CommandError('A current, guided demonstration is required to create role programs.')
                child = Child.objects.create(pk=ROLE_CHILD_IDS[name], organization=organization, code=code,
                                             age_years=5, responsible=accounts[name])
                child.varieties.add(*varieties)
            elif child.organization_id != organization.pk or not child.code.endswith('· fictif'):
                raise CommandError('A reserved role profile is not explicitly fictional.')
            if name == 'orthophoniste' and (child_created or 'accompagnant' in new_accounts):
                FamilyLink.objects.get_or_create(child=child, user=accounts['accompagnant'])
            if not child_created:
                continue
            for variety in varieties:
                activity = examples[variety.pk]
                program, created = Program.objects.get_or_create(
                    organization=organization, child=child, title='Parcours fictif · ' + variety.language,
                    defaults={'variety': variety, 'created_by': accounts[name],
                              'goal': 'Découvrir les étapes et le bilan de pratique avec des données fictives.',
                              'guidance': 'Exemple illustratif non validé, sans mesure de prononciation.',
                              'schedule': 'Démonstration accompagnée ; aucune prescription réelle.'})
                if created:
                    ProgramItem.objects.create(program=program, position=1, activity=activity)

        for name, capabilities in EDITORIAL_CAPABILITIES.items():
            for variety in varieties:
                EditorialGrant.objects.get_or_create(user=accounts[name], variety=variety, defaults=capabilities)
        accounts['gestionnaire'].user_permissions.add(
            Permission.objects.get(content_type__app_label='core', codename='manage_entitlements'))

        # Reviewers need a genuinely available review step. This material is
        # explicitly fictional; no clinical approval or recording is created.
        for variety in varieties:
            series = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-demo-role-review:' + variety.code)
            review = Activity.objects.filter(series=series, version=1).first()
            if review:
                if not review.is_demo or review.variety_id != variety.pk:
                    raise CommandError('A reserved review example is not fictitious.')
                continue
            source = examples[variety.pk]
            if source is None:
                raise CommandError('A current, guided demonstration is required to create a review example.')
            values = {field.attname: getattr(source, field.attname) for field in source._meta.concrete_fields
                      if field.name not in ['id', 'series', 'state', 'created_at', 'version']}
            values.update(title='Relecture fictive · ' + variety.language, state='review', is_demo=True,
                          population='Fictional editorial walkthrough only.',
                          limitations='Illustrative interface example, not clinically approved. No reviewed audio model.')
            review, _ = Activity.objects.get_or_create(series=series, version=1, defaults=values)
            if not review.is_demo or review.variety_id != variety.pk:
                raise CommandError('A reserved review example is not fictitious.')

        self.stdout.write(self.style.SUCCESS(
            'Role demonstration ready: ' + ', '.join(ROLE_USERNAMES) + '. Existing passwords and affiliations are not reset.'))