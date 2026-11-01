"""Rendered position labels preserve legacy protocol identity and frozen observations."""
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.models import EditorialGrant, Variety
from core.models import User
from .models import ProbeDefinition
from .tests import item


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PositionPresentationTests(TestCase):
    labels = {
        'fr': ['Début de mot', 'Intérieur du mot', 'Fin de mot', 'Première consonne'],
        'en': ['Word initial', 'Word medial', 'Word final', 'First consonant'],
        'ar': ['أول الكلمة', 'وسط الكلمة', 'آخر الكلمة', 'الصامت الأول'],
    }

    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(code='fr-position-fixture', language='fr', label='Fictional position variety')
        cls.editor = User.objects.create_user(username='protocol-position-reader', email='position-reader@example.test')
        EditorialGrant.objects.create(user=cls.editor, variety=cls.variety, edit=True)
        cls.definitions = {}
        for index, position in enumerate(('initial', 'medial', 'final', 'first_consonant')):
            cls.definitions[position] = ProbeDefinition.objects.create(
                variety=cls.variety, authored_by=cls.editor, title='Fictional position fixture '+str(index),
                protocol='Software rendering fixture only', task='Fictional naming',
                target_phoneme='p', target_position=position, target_scope={}, items=[item(0)], is_demo=True,
            )

    def setUp(self):
        self.client.force_login(self.editor)

    def test_protocol_list_renders_human_position_labels_in_all_languages(self):
        for language, labels in self.labels.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(reverse('followup:definition_list'))
                self.assertEqual(response.status_code, 200)
                for label in labels:
                    self.assertContains(response, label)
                self.assertNotContains(response, 'first_consonant')

    def test_legacy_protocol_detail_label_does_not_rewrite_code_or_fingerprint(self):
        definition = self.definitions['first_consonant']
        digest = definition.fingerprint()
        for language, labels in self.labels.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(reverse('followup:definition_detail', args=[definition.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, labels[-1])
                self.assertNotContains(response, 'first_consonant')
                definition.refresh_from_db()
                self.assertEqual(definition.target_position, 'first_consonant')
                self.assertEqual(definition.target_scope, {})
                self.assertEqual(definition.fingerprint(), digest)

    def test_frozen_goal_snapshot_uses_ui_label_and_preserves_unknown_text(self):
        snapshot = {'target_phoneme':'p', 'target_position':'first_consonant', 'target_scope':{},
                    'expected_realization':'Fictional only', 'rationale':'Fictional rationale',
                    'functional_goal':'Fictional goal', 'accepted_variants':[]}
        for language, labels in self.labels.items():
            with self.subTest(language=language), translation.override(language):
                output = render_to_string('followup/goal_snapshot.html', {'clinical_goal_snapshot':snapshot})
                self.assertIn(labels[-1], output)
                self.assertNotIn('first_consonant', output)
                self.assertEqual(snapshot['target_position'], 'first_consonant')
                custom = {**snapshot, 'target_position':'<b>custom documented position</b>'}
                output = render_to_string('followup/goal_snapshot.html', {'clinical_goal_snapshot':custom})
                self.assertIn('&lt;b&gt;custom documented position&lt;/b&gt;', output)
                self.assertNotIn('<b>custom documented position</b>', output)
