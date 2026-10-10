import os
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.utils import timezone
from core.models import User, Organization, Membership, Entitlement
from care.models import Child, FamilyLink, Program, ProgramItem
from catalog.models import Variety, Activity

class Command(BaseCommand):
    help = 'Create isolated fictitious demo data. Requires DEMO_MODE and an explicit password.'
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Only allowed with DEMO_MODE=1.')
        password = os.getenv('DEMO_PASSWORD')
        if not password or len(password) < 12:
            raise CommandError('Set DEMO_PASSWORD (at least 12 characters). No embedded credentials.')
        accounts = {}
        for name in ['praticien', 'famille', 'autre_praticien', 'editorial']:
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
            child, _ = Child.objects.get_or_create(organization=orgs[0], code=['Lina · fictif', 'Adam · fictif', 'Nour · fictif'][index], defaults={'age_years': 5 + index % 2, 'responsible': accounts['praticien']})
            child.varieties.add(variety)
            if index == 0:
                FamilyLink.objects.get_or_create(child=child, user=accounts['famille'])
            program, _ = Program.objects.get_or_create(organization=orgs[0], child=child, title='Découvrir les images · ' + language, defaults={'variety': variety, 'created_by': accounts['praticien'], 'guidance': 'Programme fictif pour découvrir le parcours.', 'schedule': 'Selon les consignes du praticien / As directed by your clinician'})
            ProgramItem.objects.get_or_create(program=program, position=1, defaults={'activity': activity})
        foreign, _ = Child.objects.get_or_create(organization=orgs[1], code='Profil B · fictif', defaults={'age_years': 6, 'responsible': accounts['autre_praticien']})
        foreign.varieties.add(Variety.objects.get(code='fr-fr-pilot'))
        editor, _ = Group.objects.get_or_create(name='Editorial')
        editor.permissions.set(Permission.objects.filter(content_type__app_label='catalog'))
        accounts['editorial'].groups.add(editor)
        from catalog.models import EditorialGrant
        for variety in Variety.objects.all():
            EditorialGrant.objects.get_or_create(user=accounts['editorial'], variety=variety, defaults={'edit': True, 'clinical_review': True, 'linguistic_review': True, 'publish': True})
        self.stdout.write(self.style.SUCCESS('Demo ready. Accounts: praticien, famille, autre_praticien, editorial. Existing passwords are not reset.'))
