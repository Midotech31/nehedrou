import hashlib
import os
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.urls import reverse
from django.core.exceptions import PermissionDenied, ValidationError
from catalog.models import Activity, EditorialGrant, Variety
from catalog.services import transition
from core.models import User, RecoveryCode
from django_otp.plugins.otp_totp.models import TOTPDevice

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class CompletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {'DEMO_PASSWORD':'Fictional-Demo-2026!'}):
            call_command('seed_demo', verbosity=0)
        call_command('seed_candidates', demo_copies=True, verbosity=0)
        cls.editor = User.objects.get(username='editorial')
        cls.family = User.objects.get(username='famille')
        cls.pro = User.objects.get(username='praticien')

    def test_candidate_catalogue_is_unapproved_and_complete(self):
        drafts = Activity.objects.filter(is_demo=False)
        self.assertEqual(drafts.count(),37)
        self.assertEqual(set(drafts.values_list('state',flat=True)),{'draft'})
        for language in ['fr','en','ar']:
            self.assertEqual(drafts.filter(variety__language=language).count(),{'fr':19,'en':17,'ar':1}[language])
        call_command('seed_candidates',demo_copies=True,verbosity=0)
        self.assertEqual(Activity.objects.filter(is_demo=False).count(),37)

    def test_family_cannot_edit_or_bill(self):
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('editorial_index')).status_code,404)
        self.assertEqual(self.client.get(reverse('billing_index')).status_code,403)

    def test_editorial_screens_render(self):
        self.client.force_login(self.editor)
        activity = Activity.objects.filter(is_demo=False).first()
        for name,args in [('editorial_index',[]),('editorial_edit',[activity.pk]),('editorial_detail',[activity.pk]),('editorial_upload',[])]:
            self.assertEqual(self.client.get(reverse(name,args=args)).status_code,200,name)

    def test_draft_cannot_skip_review(self):
        activity=Activity.objects.filter(is_demo=False).first()
        with self.assertRaises(ValidationError):
            transition(self.editor,activity.pk,'published')
        activity.refresh_from_db()
        self.assertEqual(activity.state,'draft')

    def test_grant_is_scoped_to_variety(self):
        activity=Activity.objects.filter(is_demo=False).first()
        EditorialGrant.objects.filter(user=self.editor,variety=activity.variety).delete()
        with self.assertRaises(PermissionDenied):
            transition(self.editor,activity.pk,'review')

    @override_settings(MFA_REQUIRED=True)
    def test_required_mfa_redirects_professional(self):
        self.client.force_login(self.pro)
        self.assertRedirects(self.client.get(reverse('dashboard')),reverse('mfa_setup'),fetch_redirect_response=False)

    def test_recovery_code_single_use(self):
        device=TOTPDevice.objects.create(user=self.pro,name='primary',confirmed=True)
        code='1234567890abcdef12345678'
        RecoveryCode.objects.create(user=self.pro,digest=hashlib.sha256(code.encode()).hexdigest())
        self.client.force_login(self.pro)
        response=self.client.post(reverse('mfa_verify'),{'token':code})
        self.assertEqual(response.status_code,302)
        self.assertFalse(RecoveryCode.objects.filter(user=self.pro).exists())
        self.client.logout()
        self.client.force_login(self.pro)
        response=self.client.post(reverse('mfa_verify'),{'token':code})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('otp_device_id',self.client.session)


    def test_library_language_filter_and_pagination(self):
        self.client.force_login(self.pro)
        for language in ['fr','en','ar']:
            response=self.client.get(reverse('library'), {'content_language':language})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['result_count'],{'fr':19,'en':17,'ar':1}[language])
            self.assertTrue(all(a.variety.language==language for a in response.context['page']))
            if response.context['page'].paginator.num_pages > 1:
                self.assertContains(response,'content_language='+language)
            else:
                self.assertContains(response, f'<option value="{language}" selected>')

    def test_profile_search_preserves_isolation(self):
        self.client.force_login(self.family)
        response=self.client.get(reverse('children'), {'q':'Adam','status':'all'})
        self.assertEqual(response.context['result_count'],0)
        response=self.client.get(reverse('children'), {'q':'Lina','status':'all'})
        self.assertEqual(response.context['result_count'],1)

    def test_dashboard_is_localized_in_all_three_languages(self):
        self.client.force_login(self.pro)
        for language in ['fr','en','ar']:
            response=self.client.get('/'+language+'/app/')
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.context['week']),7)
            self.assertEqual(response.context['week_total'],0)
            if language!='en':
                self.assertNotContains(response,'Practice rhythm')
                self.assertNotContains(response,'Open program')

    def test_archived_profile_closes_practice_but_keeps_history(self):
        from care.models import Child
        child = Child.objects.get(code='Lina · fictif')
        item = child.programs.get().items.get()
        child.active = False
        child.save()
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(reverse('practice', args=[item.pk])).status_code,410)
        self.assertEqual(self.client.get(reverse('program_detail', args=[item.program_id])).status_code,200)

    def test_stale_item_cannot_record_after_program_completion(self):
        import uuid
        from care.models import Child
        from core.services import record_practice
        child = Child.objects.get(code='Lina · fictif')
        item = child.programs.get().items.select_related('program','activity').get()
        program = child.programs.get()
        program.state = 'completed'
        program.save()
        with self.assertRaises(ValidationError):
            record_practice(self.family, item, {'answer':'a','completion':'completed','parent_report':'easy','comment':''}, {'target':'a','key':str(uuid.uuid4())})

    def test_help_and_role_navigation_in_three_languages(self):
        self.client.force_login(self.family)
        for code in ['fr','en','ar']:
            response=self.client.get('/'+code+'/help/')
            self.assertEqual(response.status_code,200)
            self.assertNotContains(response,'/members/')
            self.assertContains(response,'product.css')
        self.client.force_login(self.editor)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('editorial_index'))
