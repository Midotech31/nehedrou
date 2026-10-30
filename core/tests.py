import os
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from catalog.models import Activity, Review
from care.models import Child, Program, ProgramItem, FamilyLink, PracticeSession, Observation
from .testing import pcm_fixture
from .models import User, Organization, Membership, Entitlement, Invitation, AuditEvent, PrivacyRequest, RateWindow
from .services import accept_invitation, record_practice

@override_settings(DEMO_MODE=True)
class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {'DEMO_PASSWORD': 'Fictional-Demo-2026!'}):
            call_command('seed_demo', verbosity=0)
        cls.pro = User.objects.get(username='praticien')
        cls.family = User.objects.get(username='famille')
        cls.other = User.objects.get(username='autre_praticien')
        cls.child = Child.objects.get(code='Lina · fictif')
        cls.program = cls.child.programs.get()
        cls.item = cls.program.items.get()
        cls.org = cls.child.organization

    def setUp(self):
        translation.activate('fr')
        self.client.force_login(self.pro)

    def ticket(self, user=None):
        return {'user': (user or self.family).pk, 'item': str(self.item.pk), 'key': str(uuid.uuid4()), 'target': 'a'}

    def payload(self, **changes):
        data = {'answer': 'a', 'completion': 'completed', 'parent_report': 'easy', 'comment': 'Retour fictif'}
        data.update(changes)
        return data

    def test_all_main_screens_render_in_three_languages(self):
        names = ['home', 'dashboard', 'children', 'child_create', 'library', 'members', 'subscription', 'preferences']
        objects = [('child_detail', self.child.pk), ('program_create', self.child.pk), ('program_detail', self.program.pk), ('practice', self.item.pk), ('print_program', self.program.pk), ('activity_detail', self.item.activity_id)]
        for code in ['fr', 'en', 'ar']:
            with translation.override(code):
                for name in names:
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200, (code, name))
                for name, pk in objects:
                    self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 200, (code, name))
                response = self.client.get(reverse('dashboard'))
                self.assertContains(response, f'lang="{code}"')
                if code == 'ar':
                    self.assertContains(response, 'dir="rtl"')
                    self.assertContains(response, 'نظرة عامة')

    def test_foreign_practice_denied_read_write_export_print(self):
        self.client.force_login(self.other)
        for name, pk in [('child_detail', self.child.pk), ('program_create', self.child.pk), ('program_detail', self.program.pk), ('practice', self.item.pk), ('export_child', self.child.pk), ('print_program', self.program.pk), ('finish_program', self.program.pk), ('privacy_request', self.child.pk)]:
            self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 404 if name not in ['finish_program', 'privacy_request'] else 405)
            self.assertEqual(self.client.post(reverse(name, args=[pk]), {}).status_code, 404)

    def test_manager_has_no_automatic_clinical_access(self):
        user = User.objects.create_user(username='manager', email='manager@demo.example', password='example-password')
        Membership.objects.create(organization=self.org, user=user, role='owner')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('child_detail', args=[self.child.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('members')).status_code, 200)

    def test_family_cannot_see_unlinked_children_or_write_observations(self):
        self.client.force_login(self.family)
        other = Child.objects.exclude(pk=self.child.pk).first()
        self.assertEqual(self.client.get(reverse('child_detail', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('program_detail', args=[self.program.pk]), {'text': 'no'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('members')).status_code, 404)

    def test_family_revocation_removes_all_access(self):
        link = FamilyLink.objects.get(child=self.child, user=self.family)
        response = self.client.post(reverse('revoke_link', args=[link.pk]))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.family)
        for name, pk in [('child_detail', self.child.pk), ('program_detail', self.program.pk), ('practice', self.item.pk), ('export_child', self.child.pk), ('print_program', self.program.pk)]:
            self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 404)

    def test_membership_revocation_removes_professional_access(self):
        Membership.objects.filter(user=self.pro, organization=self.org).update(active=False)
        self.assertEqual(self.client.get(reverse('child_detail', args=[self.child.pk])).status_code, 404)

    def test_cross_practice_relations_rejected(self):
        org = Child.objects.filter(responsible=self.other).first().organization
        with self.assertRaises(ValidationError):
            Program.objects.create(organization=org, child=self.child, variety=self.program.variety, created_by=self.other, title='Invalid')
        with self.assertRaises(ValidationError):
            Child.objects.create(organization=org, responsible=self.pro, code='Invalid', age_years=5)
        with self.assertRaises(ValidationError):
            PracticeSession.objects.create(organization=org, item=self.item, user=self.family, idempotency_key=uuid.uuid4(), payload_digest='x', target='a', answer='a', correct=True, completion='completed', parent_report='easy')

    def test_wrong_variety_and_draft_rejected(self):
        other = Activity.objects.exclude(variety=self.program.variety).first()
        with self.assertRaises(ValidationError):
            ProgramItem.objects.create(program=self.program, activity=other, position=2)
        activity = Activity.objects.create(variety=self.program.variety, series=uuid.uuid4(), title='Draft', contrast='demo', word_a='a', word_b='b', instructions={'fr': 'demo'})
        with self.assertRaises(ValidationError):
            ProgramItem.objects.create(program=self.program, activity=activity, position=2)

    def test_published_version_is_immutable_and_withdrawal_keeps_history(self):
        activity = self.item.activity
        activity.word_a = 'Modified'
        with self.assertRaises(ValidationError):
            activity.save()
        activity.refresh_from_db()
        session = record_practice(self.family, self.item, self.payload(), self.ticket())
        activity.state = 'withdrawn'
        activity.save()
        self.assertTrue(PracticeSession.objects.filter(pk=session.pk).exists())
        self.assertEqual(self.client.get(reverse('practice', args=[self.item.pk])).status_code, 410)
        self.assertContains(self.client.get(reverse('program_detail', args=[self.program.pk])), 'Contenu retiré')

    def test_interface_language_does_not_change_program(self):
        response = self.client.post(reverse('set_language'), {'language': 'ar', 'next': reverse('dashboard')})
        self.assertEqual(response.status_code, 302)
        self.program.refresh_from_db()
        self.assertEqual(self.program.variety.language, 'fr')

    def test_missing_instruction_never_silently_falls_back(self):
        # Simulates a legacy incomplete version; normal publication rejects this state.
        Activity.objects.filter(pk=self.item.activity_id).update(instructions={'fr': 'French only'})
        self.family.instruction_language = 'ar'
        self.family.save()
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('practice', args=[self.item.pk])).status_code, 409)

    def test_submission_idempotency_and_conflicting_replay(self):
        ticket = self.ticket()
        first = record_practice(self.family, self.item, self.payload(), ticket)
        second = record_practice(self.family, self.item, self.payload(), ticket)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PracticeSession.objects.count(), 1)
        with self.assertRaises(ValidationError):
            record_practice(self.family, self.item, self.payload(answer='b'), ticket)

    def test_stopped_attempt_has_no_incorrect_score(self):
        session = record_practice(self.family, self.item, self.payload(answer='', completion='stopped'), self.ticket())
        self.assertIsNone(session.correct)
        response = self.client.get(reverse('program_detail', args=[self.program.pk]))
        self.assertEqual(response.context['stats']['answered'], 0)
        self.assertEqual(response.context['stats']['stopped'], 1)

    def test_signed_ticket_cannot_be_reused_for_another_user(self):
        self.client.force_login(self.family)
        data = self.payload(ticket=signing.dumps(self.ticket(self.pro), salt='practice'))
        response = self.client.post(reverse('practice', args=[self.item.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PracticeSession.objects.count(), 0)

    def test_practice_post_records_server_computed_result(self):
        self.client.force_login(self.family)
        data = self.payload(ticket=signing.dumps(self.ticket(), salt='practice'), correct='false')
        self.assertEqual(self.client.post(reverse('practice', args=[self.item.pk]), data).status_code, 302)
        self.assertTrue(PracticeSession.objects.get().correct)

    def test_invitation_expired_revoked_used_and_email_bound(self):
        invitation, token = Invitation.issue(self.org, self.child, self.family.email, self.pro)
        with self.assertRaises(ValidationError):
            accept_invitation(self.other, token)
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save()
        with self.assertRaises(ValidationError):
            accept_invitation(self.family, token)
        invitation.expires_at = timezone.now() + timedelta(days=1)
        invitation.revoked = True
        invitation.save()
        with self.assertRaises(ValidationError):
            accept_invitation(self.family, token)
        invitation.revoked = False
        invitation.save()
        accept_invitation(self.family, token)
        with self.assertRaises(ValidationError):
            accept_invitation(self.family, token)

    def test_member_invitation_quota(self):
        entitlement = self.org.entitlement
        entitlement.practitioner_quota = 1
        entitlement.save()
        invitation, token = Invitation.issue(self.org, None, self.other.email, self.pro, kind='clinician')
        with self.assertRaises(ValidationError):
            accept_invitation(self.other, token)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        entitlement.practitioner_quota = 2
        entitlement.save()
        accept_invitation(self.other, token)
        self.assertTrue(Membership.objects.filter(user=self.other, organization=self.org, active=True).exists())

    def test_quota_and_expiry_preserve_export(self):
        entitlement = self.org.entitlement
        entitlement.child_quota = 3
        entitlement.save()
        data = {'code': 'New fictitious profile', 'age_years': 5, 'varieties': [self.program.variety_id]}
        response = self.client.post(reverse('child_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Child.objects.filter(code=data['code']).exists())
        entitlement.expires_at = timezone.now() - timedelta(days=1)
        entitlement.save()
        self.assertEqual(self.client.get(reverse('export_child', args=[self.child.pk])).status_code, 200)
        response = self.client.post(reverse('program_create', args=[self.child.pk]), {'title': 'New', 'variety': self.program.variety_id, 'activities': [self.item.activity_id], 'guidance': '', 'schedule': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Program.objects.filter(title='New').exists())

    def test_family_export_excludes_professional_observations(self):
        Observation.objects.create(program=self.program, author=self.pro, text='Professional fictional note')
        self.client.force_login(self.family)
        result = self.client.get(reverse('export_child', args=[self.child.pk]))
        self.assertNotIn('professional_observations', result.json()['programs'][0])
        self.assertNotIn('Professional fictional note', result.content.decode())
        self.assertIn('no-store', result['Cache-Control'])

    def test_clinical_catalog_publication_is_gated(self):
        activity = Activity.objects.create(variety=self.program.variety, series=uuid.uuid4(), title='Unreviewed', contrast='x', word_a='a', word_b='b', instructions={'fr': 'x'})
        activity.is_demo = False
        activity.state = 'published'
        with self.assertRaises(ValidationError):
            activity.save()

    @override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
    def test_reviews_are_bound_to_the_exact_content(self):
        from qualification.test_support import prepare_activity_fixture
        activity = Activity.objects.create(variety=self.program.variety, series=uuid.uuid4(), title='Review fixture', contrast='example', word_a='a', word_b='b', transcription_a='/a/', transcription_b='/b/', rights='Test only', population='Fictional', instructions={'fr': 'x', 'en': 'x', 'ar': 'x'}, is_demo=False, state='review')
        prepare_activity_fixture(activity,self.pro)
        activity.word_a = 'changed'
        activity.state = 'published'
        with self.assertRaises(ValidationError):
            activity.save()
        activity.word_a = 'a'
        activity.save()
        activity.refresh_from_db()
        self.assertEqual(activity.state, 'published')

    @override_settings(DEMO_MODE=False)
    def test_demo_content_cannot_be_assigned_in_real_mode(self):
        with self.assertRaises(ValidationError):
            ProgramItem.objects.create(program=self.program, activity=self.item.activity, position=2)
        self.assertNotContains(self.client.get(reverse('library')), self.item.activity.title)

    def test_privacy_request_records_child_and_audits_without_comment(self):
        self.client.post(reverse('privacy_request', args=[self.child.pk]))
        obj = PrivacyRequest.objects.get()
        self.assertEqual(obj.child, self.child)
        self.assertTrue(AuditEvent.objects.filter(action='privacy.requested', object_id=str(obj.pk)).exists())

    def test_auth_rate_limit(self):
        self.client.logout()
        for index in range(3):
            self.assertEqual(self.client.post(reverse('login'), {'username': 'missing', 'password': 'wrong'}).status_code, 200)
        response = self.client.post(reverse('login'), {'username': 'missing', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response['Retry-After']), 0)
        self.assertEqual(self.client.post(reverse('login'), {'username': 'another-missing', 'password': 'wrong'}).status_code, 200)

    def test_csrf_blocks_mutation(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.pro)
        self.assertEqual(client.post(reverse('finish_program', args=[self.program.pk])).status_code, 403)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_recovery_is_neutral_and_single_use(self):
        from django.core import mail
        response = self.client.post(reverse('password_reset'), {'email': self.family.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.child.code, mail.outbox[0].body)
        from django.contrib.auth.tokens import default_token_generator
        token = default_token_generator.make_token(self.family)
        self.assertTrue(default_token_generator.check_token(self.family, token))
        self.family.set_password('Changed-Password-2026!')
        self.family.save()
        self.assertFalse(default_token_generator.check_token(self.family, token))

    def test_editor_has_catalog_access_without_patient_access(self):
        editor = User.objects.get(username='editorial')
        self.client.force_login(editor)
        self.assertEqual(self.client.get('/admin/catalog/activity/').status_code, 200)
        self.assertEqual(self.client.get('/admin/core/membership/').status_code, 403)
        self.assertEqual(self.client.get(reverse('export_child', args=[self.child.pk])).status_code, 404)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_full_creation_invitation_practice_and_export_workflow(self):
        from django.core import mail
        from catalog.content_catalog import current_catalog
        # New assignments use the current catalogue; the original item remains
        # unchanged for the historical-program regressions in this class.
        call_command('seed_candidates', demo_copies=True, verbosity=0)
        activity = current_catalog(Activity.objects.filter(variety=self.program.variety, is_demo=True, state='published', version=2)).order_by('series').first()
        self.assertIsNotNone(activity)
        self.assertTrue(activity.practice_guide)
        self.assertEqual(self.client.post(reverse('child_create'), {'code': 'Workflow fictif', 'age_years': 5, 'varieties': [self.program.variety_id]}).status_code, 302)
        child = Child.objects.get(code='Workflow fictif')
        self.assertEqual(self.client.post(reverse('program_create', args=[child.pk]), {'title': 'Workflow', 'variety': self.program.variety_id, 'activities': [activity.pk], 'guidance': 'Fictional guidance', 'schedule': 'Clinician chosen'}).status_code, 302)
        program = child.programs.get()
        self.assertEqual(self.client.post(reverse('child_detail', args=[child.pk]), {'email': 'workflow@demo.example'}).status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(child.code, mail.outbox[0].body)
        url = mail.outbox[0].body.splitlines()[-1]
        token = url.rstrip('/').split('/')[-1]
        user = User.objects.create_user(username='workflow-family', email='workflow@demo.example', password='Secure-Fictional-2026!')
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse('invite', args=[token])).status_code, 302)
        item = program.items.get()
        response = self.client.get(reverse('practice', args=[item.pk]))
        ticket = response.context['form'].initial['ticket']
        target = signing.loads(ticket, salt='practice')['target']
        self.assertEqual(self.client.post(reverse('practice', args=[item.pk]), self.payload(ticket=ticket, answer=target)).status_code, 302)
        result = self.client.get(reverse('export_child', args=[child.pk])).json()
        session = result['programs'][0]['items'][0]['sessions'][0]
        self.assertTrue(session['closed_task_correct'])
        self.assertEqual(session['reporter_role'], 'caregiver')

    def test_archive_frees_quota_without_deleting_history(self):
        self.assertEqual(self.client.post(reverse('archive_child', args=[self.child.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse('export_child', args=[self.child.pk])).status_code, 200)
        response = self.client.post(reverse('program_create', args=[self.child.pk]), {'title': 'Archive must block', 'variety': self.program.variety_id, 'activities': [self.item.activity_id], 'guidance': '', 'schedule': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Program.objects.filter(title='Archive must block').exists())

    def test_import_validation_is_atomic_and_draft_only(self):
        import json
        from django.core.management.base import CommandError
        from io import StringIO
        row = {'variety_code': self.program.variety.code, 'series': str(uuid.uuid4()), 'title': 'Import test', 'contrast': 'demo', 'word_a': 'a', 'word_b': 'b', 'instructions': {'fr': 'test'}}
        count = Activity.objects.count()
        with patch('catalog.management.commands.import_catalog.Path.read_text', return_value=json.dumps([row])) as source:
            file = 'fixture.json'
            call_command('import_catalog', str(file), stdout=StringIO())
            self.assertEqual(Activity.objects.count(), count)
            source.return_value = json.dumps([row, dict(row, variety_code='missing')])
            with self.assertRaises(CommandError):
                call_command('import_catalog', str(file), apply=True, stdout=StringIO())
            self.assertEqual(Activity.objects.count(), count)
            source.return_value = json.dumps([row])
            call_command('import_catalog', str(file), apply=True, stdout=StringIO())
            self.assertEqual(Activity.objects.get(title='Import test').state, 'draft')
