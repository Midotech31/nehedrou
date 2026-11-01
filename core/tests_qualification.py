import uuid
import secrets
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from catalog.models import Activity, EditorialGrant, MediaAsset, Review
from catalog.services import transition, review_version
from care.models import Child, Program, ProgramItem, PracticeSession, FamilyLink
from .forms import ProgramForm, PracticeForm
from .models import User, Invitation, AuditEvent, Membership, PrivacyRequest
from .services import create_program, record_practice, issue_and_deliver_invitation, resolve_privacy
from . import tests as original_tests
from .testing import pcm_fixture, practice_form_data
from qualification.test_support import prepare_activity_fixture, availability_fixture, competence_fixture


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class QualificationTests(TestCase):
    setUpTestData = classmethod(original_tests.WorkflowTests.setUpTestData.__func__)
    ticket = original_tests.WorkflowTests.ticket
    payload = original_tests.WorkflowTests.payload

    def setUp(self):
        translation.activate('fr')
        self.client.force_login(self.pro)

    def data(self, **changes):
        data = dict(title='Goal and guidance', goal='Fictional demonstration goal', variety=self.program.variety, activities=[self.item.activity], guidance='Fictional guidance', schedule='Chosen by clinician')
        data.update(changes)
        return data

    def candidate(self):
        return Activity.objects.create(variety=self.program.variety, series=uuid.uuid4(), title='Publication fixture', contrast='x', word_a='a', word_b='b', transcription_a='/a/', transcription_b='/b/', image_a='editorial/hat.svg', image_b='editorial/boat.svg', rights='Test fixture only', population='Fictional', instructions={'fr':'x','en':'x','ar':'x'}, is_demo=False, state='review')

    def reviews(self, activity):
        # Exact-byte media, documentary evidence and two independent reviewers.
        self.linguistic_reviewer = prepare_activity_fixture(activity, self.pro)
        availability_fixture('practice', activity.variety, activity.fingerprint(), self.pro)

    def test_stale_assignment_rejects_archived_withdrawn_or_transferred(self):
        Child.objects.filter(pk=self.child.pk).update(active=False)
        with self.assertRaises(ValidationError): create_program(self.pro,self.child,self.data())
        Child.objects.filter(pk=self.child.pk).update(active=True)
        Activity.objects.filter(pk=self.item.activity_id).update(state='withdrawn')
        with self.assertRaises(ValidationError): create_program(self.pro,self.child,self.data())
        Activity.objects.filter(pk=self.item.activity_id).update(state='published')
        Membership.objects.create(organization=self.org,user=self.other,role='clinician')
        Child.objects.filter(pk=self.child.pk).update(responsible=self.other)
        with self.assertRaises(ValidationError): create_program(self.pro,self.child,self.data())
        self.assertEqual(Program.objects.filter(child=self.child).count(),1)

    @override_settings(DEMO_MODE=False)
    def test_legacy_demo_program_cannot_be_practiced_or_printed_in_real_mode(self):
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('practice',args=[self.item.pk])).status_code,410)
        self.assertEqual(self.client.post(reverse('practice',args=[self.item.pk]),self.payload()).status_code,410)
        with self.assertRaises(ValidationError): record_practice(self.family,self.item,self.payload(),self.ticket())
        self.assertEqual(PracticeSession.objects.count(),0)
        self.assertNotContains(self.client.get(reverse('program_detail',args=[self.program.pk])),reverse('practice',args=[self.item.pk]))
        self.assertNotContains(self.client.get(reverse('print_program',args=[self.program.pk])),'editorial/hat.svg')

    @override_settings(MFA_REQUIRED=True)
    def test_mfa_covers_nonstaff_editorial_and_billing_get_and_post(self):
        editor = User.objects.create_user(username='scoped-editor',email='editor@fictional.example')
        EditorialGrant.objects.create(user=editor,variety=self.program.variety,edit=True,publish=True)
        operator = User.objects.create_user(username='operator',email='operator@fictional.example')
        operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        for actor,name in [(editor,'editorial_index'),(operator,'billing_index')]:
            self.client.force_login(actor)
            for method in [self.client.get,self.client.post]:
                response=method(reverse(name))
                self.assertRedirects(response,reverse('mfa_setup'),fetch_redirect_response=False)
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code,200)

    def test_external_missing_or_wrong_kind_audio_cannot_publish(self):
        activity=self.candidate()
        activity.audio_a=activity.audio_b='https://unavailable.invalid/a.wav'; activity.save()
        activity.state='published'
        with self.assertRaises(ValidationError): activity.save()
        activity.state='review'; self.reviews(activity)
        asset=MediaAsset.objects.get(pk=activity.audio_a.rstrip('/').split('/')[-1])
        MediaAsset.objects.filter(pk=asset.pk).update(kind='image')
        activity.state='published'
        with self.assertRaises(ValidationError): activity.save()
        MediaAsset.objects.filter(pk=asset.pk).update(kind='audio'); asset.file.delete(save=False)
        with self.assertRaises(ValidationError): activity.save()

    def test_current_rejection_blocks_approval_and_publication(self):
        activity=self.candidate(); self.reviews(activity)
        publisher=User.objects.get(username='editorial')
        competence_fixture(publisher,activity.variety,'clinical')
        transition(publisher,activity.pk,'approved')
        review_version(publisher,activity,'clinical',False,'Rejected fixture',expected_digest=activity.fingerprint())
        with self.assertRaises(ValidationError): transition(publisher,activity.pk,'published')
        review_version(publisher,activity,'clinical',True,'New approved fixture',expected_digest=activity.fingerprint())
        self.assertEqual(transition(publisher,activity.pk,'published').state,'published')
        self.assertEqual(activity.reviews.count(),4)

    @override_settings(DEMO_MODE=False)
    def test_missing_published_audio_refuses_new_practice_and_assignment(self):
        activity=self.candidate(); self.reviews(activity)
        activity.state='published';activity.save()
        item=ProgramItem.objects.create(program=self.program,activity=activity,position=2)
        asset=MediaAsset.objects.get(pk=activity.audio_a.rstrip('/').split('/')[-1])
        asset.file.delete(save=False)
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('practice',args=[item.pk])).status_code,410)
        with self.assertRaises(ValidationError): create_program(self.pro,self.child,self.data(activities=[activity]))
        with self.assertRaises(ValidationError): record_practice(self.family,item,self.payload(),self.ticket())
        self.assertEqual(PracticeSession.objects.count(),0)

    def test_existing_account_invitation_proposes_login_without_500(self):
        invitation,token=Invitation.issue(self.org,self.child,self.family.email.upper(),self.pro)
        self.client.logout()
        password = secrets.token_urlsafe(24)
        response=self.client.post(reverse('invite',args=[token]),{'username':'different','instruction_language':'fr','password1':password,'password2':password})
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.context['form'])
        self.assertFalse(User.objects.filter(username='different').exists())
        invitation.refresh_from_db(); self.assertTrue(invitation.available)
        self.client.force_login(self.family)
        self.assertEqual(self.client.post(reverse('invite',args=[token])).status_code,302)
        invitation.refresh_from_db(); self.assertIsNotNone(invitation.used_at)

    def test_smtp_failure_is_audited_and_retry_replaces_the_link(self):
        with patch('django.core.mail.send_mail',side_effect=OSError('unavailable')):
            for kind,child in [('family',self.child),('clinician',None)]:
                path = reverse('child_detail', args=[child.pk]) if child else reverse('members')
                data = {'email':kind+'@fictional.example'}
                if child is None:
                    data = practice_form_data(self.client, path, data)
                response = self.client.post(path, data)
                self.assertEqual(response.status_code,302)
                invite=Invitation.objects.get(email=kind+'@fictional.example')
                self.assertEqual(invite.delivery,'failed')
                self.assertTrue(AuditEvent.objects.filter(action='invitation.created',object_id=str(invite.pk)).exists())
                self.assertTrue(AuditEvent.objects.filter(action='invitation.delivery_failed',object_id=str(invite.pk)).exists())
                old_hash=invite.token_hash
                with patch('django.core.mail.send_mail',return_value=1):
                    self.assertEqual(self.client.post(reverse('resend_invitation',args=[invite.pk])).status_code,302)
                invite.refresh_from_db(); self.assertTrue(invite.revoked)
                replacement=Invitation.objects.get(email=invite.email,revoked=False)
                self.assertNotEqual(replacement.token_hash,old_hash)
        self.assertEqual(FamilyLink.objects.filter(child=self.child).count(),1)

    def test_erasure_rechecks_current_responsibility_and_retention(self):
        obj=PrivacyRequest.objects.create(organization=self.org,child=self.child,requester=self.family,kind='erasure')
        self.org.retention_days=0; self.org.save()
        data={'decision':'erase','confirmation':self.child.code,'reason':'Fictional request'}
        Membership.objects.create(organization=self.org,user=self.other,role='clinician')
        Child.objects.filter(pk=self.child.pk).update(responsible=self.other)
        with self.assertRaises(ValidationError): resolve_privacy(self.pro,obj.pk,data)
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        Child.objects.filter(pk=self.child.pk).update(responsible=self.pro)
        self.org.retention_days=1; self.org.save()
        with self.assertRaises(ValidationError): resolve_privacy(self.pro,obj.pk,data)
        obj.refresh_from_db(); self.assertEqual(obj.status,'pending')

    def test_program_preview_creates_nothing_and_order_is_validated(self):
        from django.core.management import call_command
        from catalog.content_catalog import current_catalog
        call_command('seed_candidates', demo_copies=True, verbosity=0)
        copy, other = list(current_catalog(Activity.objects.filter(variety=self.program.variety, is_demo=True, state='published', version=2)).order_by('series')[:2])
        self.assertTrue(copy.practice_guide)
        self.assertTrue(other.practice_guide)
        data={'title':'Ordered program','variety':copy.variety_id,'activities':[str(copy.pk),str(other.pk)],'activity_order':str(other.pk)+','+str(copy.pk),'goal':'Example goal','guidance':'Example guidance','schedule':'Chosen routine','action':'preview'}
        response=self.client.post(reverse('program_create',args=[self.child.pk]),data)
        self.assertEqual(response.status_code,200); self.assertIsNotNone(response.context['preview'])
        self.assertFalse(Program.objects.filter(title='Ordered program').exists())
        data['action']='assign'
        self.assertEqual(self.client.post(reverse('program_create',args=[self.child.pk]),data).status_code,302)
        program=Program.objects.get(title='Ordered program')
        self.assertEqual(list(program.items.values_list('activity_id',flat=True)),[other.pk,copy.pk])
        data['activity_order']=str(uuid.uuid4())
        self.assertFalse(ProgramForm(data,child=self.child).is_valid())

    def test_reports_require_explicit_responses_and_stop_discards_answer(self):
        form=PracticeForm({'ticket':'x','answer':'a'})
        self.assertFalse(form.is_valid()); self.assertIn('completion',form.errors); self.assertIn('parent_report',form.errors)
        form=PracticeForm({'ticket':'x','answer':'a','completion':'stopped','parent_report':'help'})
        self.assertTrue(form.is_valid()); self.assertEqual(form.cleaned_data['answer'],'')

    def test_family_has_direct_action_and_saved_report_is_private(self):
        self.client.force_login(self.family)
        self.assertContains(self.client.get(reverse('dashboard')),reverse('practice_run_start',args=[self.program.pk]))
        report=record_practice(self.family,self.item,self.payload(),self.ticket())
        for lang in ['fr','en','ar']:
            with translation.override(lang):
                self.assertEqual(self.client.get(reverse('practice_report',args=[report.pk])).status_code,200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('practice_report',args=[report.pk])).status_code,404)

    def test_weekly_attention_does_not_include_foreign_profiles(self):
        record_practice(self.family,self.item,self.payload(parent_report='help'),self.ticket())
        response=self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['weekly_help'],1)
        self.assertEqual(response.context['attention_programs'][0].pk,self.program.pk)
        self.client.force_login(self.other)
        response=self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['weekly_help'],0)
        self.assertEqual(response.context['attention_programs'],[])
