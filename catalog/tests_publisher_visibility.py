"""Read-only role visibility with fictional local permission fixtures only."""
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision, ReviewerCompetenceDecision
from .models import Activity, EditorialGrant, EditorialAccessInvitation, Review, Variety


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PublisherVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety=Variety.objects.create(code='ar-visibility-fixture',language='ar',label='Fictional scoped variety')
        cls.manager=User.objects.create_user('visibility-manager','manager@visibility.example.test')
        cls.manager.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.publisher=User.objects.create_user('visibility-publisher','publisher@visibility.example.test')
        cls.publisher_grant=EditorialGrant.objects.create(user=cls.publisher,variety=cls.variety,publish=True)
        cls.editor=User.objects.create_user('visibility-editor','editor@visibility.example.test')
        cls.editor_grant=EditorialGrant.objects.create(user=cls.editor,variety=cls.variety,edit=True)
        cls.reviewer=User.objects.create_user('visibility-reviewer','reviewer@visibility.example.test')
        EditorialGrant.objects.create(user=cls.reviewer,variety=cls.variety,clinical_review=True)
        cls.ordinary=User.objects.create_user('visibility-ordinary','ordinary@visibility.example.test')
        cls.empty=User.objects.create_user('visibility-no-capability','empty@visibility.example.test')
        EditorialGrant.objects.create(user=cls.empty,variety=cls.variety)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.manager)

    def page(self):
        return self.client.get(reverse('editorial_access_management'))

    def test_publisher_only_is_visible_and_empty_grant_is_excluded(self):
        response=self.page()
        self.assertEqual(response.status_code,200)
        visible={grant.user_id for grant in response.context['grants']}
        self.assertEqual(visible,{self.publisher.pk,self.editor.pk,self.reviewer.pk})
        self.assertContains(response,self.publisher.username)
        self.assertNotContains(response,self.empty.username)
        self.assertNotContains(response,'No active editorial permissions.')

    def test_gets_in_three_languages_are_read_only_and_explain_operator_management(self):
        before=list(EditorialGrant.objects.order_by('pk').values())
        counts=[model.objects.count() for model in [AuditEvent,EditorialAccessInvitation,Review,
            ReviewerCompetenceDecision,AvailabilityDecision,Activity]]
        messages={
            'en':'An authorised operator manages publishing access for this spoken variety.',
            'fr':'Un opérateur habilité gère le droit de publication pour cette variété parlée.',
            'ar':'يدير مشغّل مخوّل صلاحية النشر لهذه اللغة أو اللهجة.',
        }
        for language,message in messages.items():
            with self.subTest(language=language),translation.override(language):
                response=self.page()
                self.assertContains(response,message)
                self.assertNotContains(response,reverse('editorial_capability_revoke',args=[self.publisher_grant.pk,'publish']))
                choices={value for value,_label in response.context['form'].fields['capability'].choices}
                self.assertEqual(choices,{'edit','clinical_review','linguistic_review'})
        self.assertEqual(before,list(EditorialGrant.objects.order_by('pk').values()))
        self.assertEqual(counts,[model.objects.count() for model in [AuditEvent,EditorialAccessInvitation,Review,
            ReviewerCompetenceDecision,AvailabilityDecision,Activity]])

    def test_publishing_or_other_limited_roles_do_not_grant_platform_management(self):
        for user in [self.publisher,self.editor,self.reviewer,self.ordinary]:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response=self.page()
                self.assertEqual(response.status_code,403)
                self.assertNotContains(response,self.publisher.email,status_code=403)
        self.client.logout()
        self.assertEqual(self.page().status_code,302)

    def test_forged_publishing_invitation_and_revocation_still_cannot_change_it(self):
        response=self.client.post(reverse('editorial_access_management'),{
            'email':'new-publisher@visibility.example.test','variety':self.variety.pk,'capability':'publish'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(EditorialAccessInvitation.objects.exists())
        response=self.client.post(reverse('editorial_capability_revoke',args=[self.publisher_grant.pk,'publish']))
        self.assertEqual(response.status_code,302)
        self.publisher_grant.refresh_from_db()
        self.assertTrue(self.publisher_grant.publish)
        self.assertFalse(AuditEvent.objects.filter(action__startswith='catalog.publishing_access_').exists())

    def test_existing_limited_revocation_keeps_the_publisher_only_row_visible(self):
        self.publisher_grant.edit=True;self.publisher_grant.save()
        response=self.client.post(reverse('editorial_capability_revoke',args=[self.publisher_grant.pk,'edit']))
        self.assertEqual(response.status_code,302)
        self.publisher_grant.refresh_from_db()
        self.assertFalse(self.publisher_grant.edit)
        self.assertTrue(self.publisher_grant.publish)
        response=self.page()
        self.assertContains(response,self.publisher.username)
        self.assertIn(self.publisher_grant.pk,{grant.pk for grant in response.context['grants']})
