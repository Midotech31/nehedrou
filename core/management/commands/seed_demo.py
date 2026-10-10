import os
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import Permission
from django.db import transaction
from django.utils import timezone
from core.models import User, Organization, Membership, Entitlement
from care.models import Child, FamilyLink, Program, ProgramItem
from catalog.models import Variety, Activity

LEGACY_DEMO_USERNAMES = ('praticien', 'famille', 'autre_praticien', 'editorial')
DEMO_VARIETY_CODES = ('fr-fr-pilot', 'en-us-general-pilot', 'ar-dz-pilot')


def validate_demo_account(username, *, allow_staff=False):
    """Never attach demonstration rights to an unrelated existing account."""
    email = username + '@demo.example'
    user = User.objects.filter(username=username).first()
    if user and (user.email.lower() != email or user.is_superuser or (user.is_staff and not allow_staff)):
        raise CommandError(f'Refusing to reuse non-fictional or privileged account: {username}.')
    if User.objects.filter(email__iexact=email).exclude(username=username).exists():
        raise CommandError(f'Demonstration email already belongs to another account: {username}.')
    if user:
        known_practices = ('Cabinet Démonstration', 'Cabinet Exemple B')
        non_fictional_memberships = Membership.objects.filter(user=user).exclude(
            organization__name__in=known_practices).exclude(organization__name__endswith='· fictif')
        non_fictional_links = FamilyLink.objects.filter(user=user).exclude(
            child__organization__name__in=known_practices).exclude(child__organization__name__endswith='· fictif')
        if (non_fictional_memberships.exists() or non_fictional_links.exists()
                or Child.objects.filter(responsible=user).exclude(code__endswith='· fictif').exists()
                or FamilyLink.objects.filter(user=user).exclude(child__code__endswith='· fictif').exists()):
            raise CommandError(f'An existing affiliation is not explicitly fictional: {username}.')
    return user


def demo_password(variable='DEMO_PASSWORD'):
    password = os.getenv(variable) or os.getenv('DEMO_PASSWORD')
    if not password or len(password) < 12:
        raise CommandError(f'Set {variable} (at least 12 characters). No embedded credentials.')
    return password


class Command(BaseCommand):
    help = 'Create isolated fictitious demo data. Requires DEMO_MODE and an explicit password.'
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Only allowed with DEMO_MODE=1.')
        password = demo_password()
        for name in LEGACY_DEMO_USERNAMES:
            validate_demo_account(name, allow_staff=name == 'editorial')
        # These names predate the UUID-marked role demonstration. Refuse a
        # same-name practice if its existing records are not explicitly fictitious.
        for name, owner in [('Cabinet Démonstration', 'praticien'), ('Cabinet Exemple B', 'autre_praticien')]:
            matches = Organization.objects.filter(name=name)
            if matches.count() > 1:
                raise CommandError(f'Ambiguous demonstration practice: {name}.')
            organization = matches.first()
            if organization and (not Membership.objects.filter(organization=organization, user__username=owner).exists()
                                 or Membership.objects.filter(organization=organization).exclude(user__email__iendswith='@demo.example').exists()
                                 or Child.objects.filter(organization=organization).exclude(code__endswith='· fictif').exists()):
                raise CommandError(f'Refusing to reuse a practice without fictitious affiliation: {name}.')
        accounts = {}
        for name in LEGACY_DEMO_USERNAMES:
            user, created = User.objects.get_or_create(username=name, defaults={'email': name + '@demo.example', 'is_staff': name == 'editorial'})
            if created:
                user.set_password(password)
                user.save()
            accounts[name] = user
        orgs = []
        for index, name in enumerate(['Cabinet Démonstration', 'Cabinet Exemple B']):
            org, _ = Organization.objects.get_or_create(name=name)
            actor = accounts['praticien' if index == 0 else 'autre_praticien']
            Membership.objects.get_or_create(organization=org, user=actor, defaults={'role': 'owner'})
            Entitlement.objects.get_or_create(organization=org, defaults={'expires_at': timezone.now() + timedelta(days=30)})
            orgs.append(org)
        definitions = [
            ('fr-fr-pilot', 'fr', 'Français de France · démonstration', 'chapeau', 'bateau', 'hat', 'boat'),
            ('en-us-general-pilot', 'en', 'General American English · demonstration', 'hat', 'boat', 'hat', 'boat'),
            ('ar-dz-pilot', 'ar', 'العربية الجزائرية · مثال غير معتمد', 'قبعة', 'قارب', 'hat', 'boat'),
        ]
        for index, (code, language, label, a, b, image_a, image_b) in enumerate(definitions):
            variety, _ = Variety.objects.get_or_create(code=code, defaults={'language': language, 'label': label, 'scope': 'Demonstration only; no evaluated regional coverage.'})
            series = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-demo:' + code)
            activity, _ = Activity.objects.get_or_create(series=series, version=1, defaults={'variety': variety, 'title': a + ' / ' + b, 'word_a': a, 'word_b': b, 'contrast': 'Exemple illustratif / illustrative example', 'image_a': 'editorial/' + image_a + '.svg', 'image_b': 'editorial/' + image_b + '.svg', 'instructions': {'fr': 'Nommez les images ensemble. Faites un choix puis un petit échange, sans pression.', 'en': 'Name the pictures together. Make a choice, then enjoy a short exchange without pressure.', 'ar': 'سمّوا الصور معًا، ثم اختاروا صورة وتبادلوا حديثًا قصيرًا دون ضغط.'}, 'state': 'published', 'rights': 'Original SVG illustrations created for this project, distributed under the project MIT license.', 'population': 'Fictional demo profiles only.', 'limitations': 'These words are NOT approved minimal pairs. No clinical validity, audio model or phonetic transcription is supplied.', 'is_demo': True})
            if not activity.is_demo or activity.variety_id != variety.pk:
                raise CommandError('A reserved demonstration activity is not fictitious.')
            child, _ = Child.objects.get_or_create(organization=orgs[0], code=['Lina · fictif', 'Adam · fictif', 'Nour · fictif'][index], defaults={'age_years': 5 + index % 2, 'responsible': accounts['praticien']})
            child.varieties.add(variety)
            if index == 0:
                FamilyLink.objects.get_or_create(child=child, user=accounts['famille'])
            program, _ = Program.objects.get_or_create(organization=orgs[0], child=child, title='Découvrir les images · ' + language, defaults={'variety': variety, 'created_by': accounts['praticien'], 'guidance': 'Programme fictif pour découvrir le parcours.', 'schedule': 'Selon les consignes du praticien / As directed by your clinician'})
            ProgramItem.objects.get_or_create(program=program, position=1, defaults={'activity': activity})
        foreign, _ = Child.objects.get_or_create(organization=orgs[1], code='Profil B · fictif', defaults={'age_years': 6, 'responsible': accounts['autre_praticien']})
        foreign.varieties.add(Variety.objects.get(code='fr-fr-pilot'))
        # Do not change a shared group that could contain real users. The legacy
        # fictitious editor retains its own permissions and scoped grants.
        accounts['editorial'].user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog'))
        from catalog.models import EditorialGrant
        for variety in Variety.objects.filter(code__in=DEMO_VARIETY_CODES):
            EditorialGrant.objects.get_or_create(user=accounts['editorial'], variety=variety, defaults={'edit': True, 'clinical_review': True, 'linguistic_review': True, 'publish': True})
        self.stdout.write(self.style.SUCCESS('Demo ready. Accounts: praticien, famille, autre_praticien, editorial. Existing passwords are not reset.'))
