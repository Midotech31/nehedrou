"""Optional fiction-only setup, never a real clinical approval."""
import copy
import json
import uuid
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from care.models import Child
from core.models import User, Membership
from followup.imports import import_definitions
from followup.models import ProbeDefinition, ClinicalGoal, ParentCoaching
from followup.validation import word_key
from core.management.commands.seed_demo import validate_demo_account

# Explicit fictional adult instruction translations, never clinical approval.
COACHING_TEXT = {
    'fr': {
        'instructions': 'Simulation : découvrez ensemble uniquement les images de pratique. Suivez les consignes choisies par l’orthophoniste. Arrêtez si l’enfant est fatigué ou contrarié. Les mots réservés au suivi restent au cabinet.',
        'example': 'L’adulte montre une image de pratique et invite à un bref échange bienveillant, sans noter la prononciation.',
        'accompanied_trial': 'À montrer avec l’orthophoniste. Cette fiche fictive ne déclare pas qu’un essai réel a eu lieu.',
    },
    'en': {
        'instructions': 'Simulation: discover only the practice pictures together. Follow the instructions selected by the clinician. Stop if the child is tired or upset. Words reserved for follow-up stay with the clinician.',
        'example': 'The adult shows a practice picture and invites a short, kind exchange without rating pronunciation.',
        'accompanied_trial': 'To be demonstrated with the clinician. This fictional example does not assert that a real trial occurred.',
    },
    'ar': {
        'instructions': 'محاكاة: اكتشفوا معًا صور التدريب فقط. اتبعوا التعليمات التي اختارها أخصائي النطق. توقفوا إذا كان الطفل متعبًا أو منزعجًا. تبقى الكلمات المحجوزة للمتابعة لدى الأخصائي.',
        'example': 'يعرض المرافق صورة للتدريب ويدعو إلى حوار قصير ولطيف، دون تقييم النطق.',
        'accompanied_trial': 'يُعرض المثال مع أخصائي النطق. لا تؤكد هذه البطاقة الافتراضية حدوث محاولة حقيقية.',
    },
}

class Command(BaseCommand):
    help = 'Create two explicitly unapproved follow-up simulations for existing fictitious role accounts.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Only allowed with DEMO_MODE=1.')
        professional = validate_demo_account('orthophoniste')
        child = Child.objects.filter(code='Sami · fictif', responsible=professional).first() if professional else None
        if not child or not Membership.objects.filter(user=professional, organization=child.organization, active=True).exists():
            raise CommandError('Initialize the explicit fictional role practice first.')
        source = Path(__file__).resolve().parents[2] / 'data' / 'probes_draft.json'
        originals = import_definitions(json.loads(source.read_text(encoding='utf-8')))
        for definition, _ in originals:
            series = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-followup-simulation:' + str(definition.series))
            values = {k: copy.deepcopy(getattr(definition, k)) for k in ['variety', 'title', 'protocol', 'task', 'target_phoneme', 'target_position', 'items', 'rights', 'rights_status', 'evidence']}
            values.update(title='Simulation · ' + definition.variety.language, is_demo=True, state='draft',
                target_scope={'position': 'initial', 'context': 'fictitious_simulation'})
            demo, created = ProbeDefinition.objects.get_or_create(series=series, version=1, defaults=values)
            if not demo.is_demo or demo.variety_id != definition.variety_id:
                raise CommandError('A reserved demonstration definition is not fictional.')
            if not child.varieties.filter(pk=demo.variety_id).exists():
                continue
            gid = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-followup-goal:' + str(child.pk) + ':' + str(series))
            goal, created = ClinicalGoal.objects.get_or_create(pk=gid, defaults={
                'organization': child.organization, 'child': child, 'author': professional, 'variety': demo.variety,
                'target_phoneme': demo.target_phoneme, 'target_position': demo.target_position, 'target_scope': copy.deepcopy(demo.target_scope),
                'rationale': 'Fictional interface example; the target has not been clinically selected.',
                'expected_realization': 'Proposed initial /p/, not clinically approved.',
                'functional_goal': 'Understand descriptive manual follow-up with fictitious observations.',
                'external_assessment_status': 'not_recorded', 'probe_definition': demo,
                'reserved_words': [word_key(i['word']) for i in demo.items if i['exposure_plan'] == 'reserved']})
            if goal.child_id != child.pk or goal.author_id != professional.pk:
                raise CommandError('A reserved demonstration goal is not fictional.')
            # Preserve earlier instruction records; new UUIDs include adult language.
            for language, content in COACHING_TEXT.items():
                cid = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-followup-coaching:' + str(gid) + ':' + language)
                coaching, _ = ParentCoaching.objects.get_or_create(pk=cid, defaults={
                    'organization': child.organization, 'child': child, 'author': professional, 'variety': demo.variety,
                    'instruction_language': language, **content,
                    'understanding_checked': False, 'clinician_note': 'Fictitious unreviewed coaching fixture; no clinical approval.'})
                if coaching.child_id != child.pk or coaching.author_id != professional.pk or coaching.variety_id != demo.variety_id or coaching.instruction_language != language:
                    raise CommandError('A reserved coaching fixture is not fictional.')
        self.stdout.write('Two original unapproved drafts and fictional simulations available. No review, release or human approval created.')
