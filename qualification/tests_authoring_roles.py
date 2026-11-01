"""Authoring forms follow capabilities without granting reviewers editing access."""
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.models import EditorialGrant
from core.models import User
from followup.models import ProbeDefinition
from followup.tests import install_fixture, definition
from .models import LexicalCandidate, LexicalPack


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AuthoringFormRoleTests(TestCase):
    def setUp(self):
        install_fixture(self)
        grant = EditorialGrant.objects.get(user=self.editor, variety=self.variety)
        grant.publish = False
        grant.save()
        self.probe = definition(self, 1)
        self.pack = LexicalPack.objects.create(
            variety=self.variety, created_by=self.editor, series=uuid.uuid4(),
            title='Fictional authoring form', region='Fictional region', scope='Software test only',
            population='No real participants', indications='No clinical indication claimed', limits='Not approved',
        )
        self.candidate = LexicalCandidate.objects.create(
            pack=self.pack, word='fixture', meaning='Fictional concept', role='training', provenance='Software test only')
        self.read_only = []
        for capability in ('clinical_review', 'linguistic_review', 'publish'):
            actor = User.objects.create_user(username='authoring-'+capability, email=capability+'@example.test')
            EditorialGrant.objects.create(user=actor, variety=self.variety, **{capability:True})
            self.read_only.append(actor)

    def counts(self):
        return (LexicalPack.objects.count(), LexicalCandidate.objects.count(), ProbeDefinition.objects.count())

    def test_new_pack_get_and_forged_post_require_edit_in_all_interface_languages(self):
        original = self.counts()
        for actor in self.read_only:
            self.client.force_login(actor)
            for language in ('fr', 'en', 'ar'):
                with self.subTest(actor=actor.username, language=language), translation.override(language):
                    path = reverse('qualification:pack_new')
                    self.assertEqual(self.client.get(path).status_code, 403)
                    data = {name:getattr(self.pack, name) for name in ('title','region','scope','population','indications','limits')}
                    self.assertEqual(self.client.post(path, {**data,'variety':str(self.variety.pk)}).status_code,403)
                    self.assertEqual(self.counts(),original)

    def test_other_authoring_routes_keep_existing_read_only_role_refusals(self):
        original = self.counts()
        with translation.override('en'):
            paths = [
                (reverse('qualification:pack_edit', args=[self.pack.pk]),404),
                (reverse('qualification:candidate_new', args=[self.pack.pk]),404),
                (reverse('qualification:candidate_edit', args=[self.pack.pk,self.candidate.pk]),404),
                (reverse('followup:definition_create'),403),
                (reverse('followup:definition_edit', args=[self.probe.pk]),403),
            ]
            for actor in self.read_only:
                self.client.force_login(actor)
                for path,status in paths:
                    with self.subTest(actor=actor.username,path=path):
                        self.assertEqual(self.client.get(path).status_code,status)
                        self.assertEqual(self.client.post(path, {'title':'Forbidden authoring attempt'}).status_code,status)
                        self.assertEqual(self.counts(),original)

    def test_edit_only_author_and_practice_clinician_keep_permitted_forms(self):
        self.assertFalse(EditorialGrant.objects.get(user=self.editor,variety=self.variety).publish)
        self.assertFalse(EditorialGrant.objects.filter(user=self.pro).exists())
        for actor,routes in [
                (self.editor,[('qualification:pack_new',[]),('qualification:candidate_edit',[self.pack.pk,self.candidate.pk]),('followup:definition_create',[])]),
                (self.pro,[('followup:definition_create',[]),('followup:definition_edit',[self.probe.pk])])]:
            self.client.force_login(actor)
            for language in ('fr','en','ar'):
                with translation.override(language):
                    for name,args in routes:
                        with self.subTest(actor=actor.username,language=language,route=name):
                            self.assertEqual(self.client.get(reverse(name,args=args)).status_code,200)
        self.assertFalse(EditorialGrant.objects.filter(user=self.pro).exists())
