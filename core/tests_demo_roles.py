"""Fictional role logins, scoped capabilities, and safe initialization."""
import html
import io
import os
import re
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from care.models import Child, FamilyLink, Observation, PracticeSession, Program, ProgramItem
from catalog.models import Activity, EditorialGrant, Review, Variety
from core.management.commands.seed_demo import LEGACY_DEMO_USERNAMES
from core.management.commands.seed_demo_roles import ROLE_PASSWORD_ENV, ROLE_PRACTICE_ID, ROLE_PRACTICE_NAME, ROLE_USERNAMES
from core.models import Entitlement, Membership, Organization, User


# Synthetic test credentials only. The deployed values never enter this file.
TEST_ENV = {'DEMO_PASSWORD': 'Fictional-legacy-test-only-2026'}
TEST_ENV.update({variable: 'Fictional-role-test-only-' + name for name, variable in ROLE_PASSWORD_ENV.items()})


def seed(command='seed_demo_roles', env=None):
    output = io.StringIO()
    with patch.dict(os.environ, env or TEST_ENV):
        call_command(command, verbosity=0, stdout=output)
    return output.getvalue()


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DemoRoleInitializationTests(TestCase):
    def test_real_mode_rejects_both_initializers_without_writes(self):
        with override_settings(DEMO_MODE=False):
            for command in ['seed_demo', 'seed_demo_roles']:
                with self.assertRaises(CommandError):
                    seed(command)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Organization.objects.count(), 0)

    def test_username_collision_leaves_real_account_and_data_untouched(self):
        for command, username in [('seed_demo', 'editorial'), ('seed_demo_roles', 'orthophoniste')]:
            with self.subTest(command=command):
                account = User.objects.create_user(username=username, email=username + '@real.example', password='Real-account-test-only')
                password = account.password
                with self.assertRaises(CommandError):
                    seed(command)
                account.refresh_from_db()
                self.assertEqual(account.password, password)
                self.assertFalse(account.is_staff)
                self.assertFalse(account.user_permissions.exists())
                self.assertFalse(Membership.objects.exists())
                self.assertFalse(EditorialGrant.objects.exists())
                self.assertFalse(Organization.objects.exists())
                account.delete()

    def test_casefold_email_collision_is_rejected_before_initialization(self):
        User.objects.create_user(username='existing-real-user', email='ORTHOPHONISTE@demo.example', password='Real-account-test-only')
        with self.assertRaises(CommandError):
            seed()
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(Organization.objects.exists())

    def test_privileged_existing_demo_name_is_not_reused(self):
        for attribute in ['is_staff', 'is_superuser']:
            with self.subTest(attribute=attribute):
                account = User.objects.create_user(username='gestionnaire', email='gestionnaire@demo.example', password='Privileged-test-only', **{attribute: True})
                with self.assertRaises(CommandError):
                    seed()
                self.assertFalse(Organization.objects.exists())
                account.delete()

    def test_nonfictional_affiliation_is_preserved_and_not_expanded(self):
        account = User.objects.create_user(username='orthophoniste', email='orthophoniste@demo.example', password='Existing-test-only')
        organization = Organization.objects.create(name='Real existing practice')
        member = Membership.objects.create(organization=organization, user=account, role='clinician')
        with self.assertRaises(CommandError):
            seed()
        member.refresh_from_db()
        self.assertEqual(member.role, 'clinician')
        self.assertTrue(member.active)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertFalse(User.objects.filter(username='praticien').exists())

    def test_reserved_practice_collision_is_not_overwritten(self):
        organization = Organization.objects.create(pk=ROLE_PRACTICE_ID, name='Real existing practice')
        with self.assertRaises(CommandError):
            seed()
        organization.refresh_from_db()
        self.assertEqual(organization.name, 'Real existing practice')
        self.assertFalse(User.objects.exists())

    def test_short_role_password_rolls_back_whole_seed(self):
        with self.assertRaises(CommandError):
            seed(env={**TEST_ENV, ROLE_PASSWORD_ENV['gestionnaire']: 'short'})
        self.assertFalse(User.objects.exists())
        self.assertFalse(Organization.objects.exists())

    def test_shared_editorial_group_is_not_modified(self):
        group = Group.objects.create(name='Editorial')
        permission = Permission.objects.get(content_type__app_label='catalog', codename='view_activity')
        group.permissions.add(permission)
        actual = User.objects.create_user(username='actual-editor', email='actual@real.example', password='Real-account-test-only')
        actual.groups.add(group)
        seed('seed_demo')
        self.assertEqual(set(group.permissions.values_list('pk', flat=True)), {permission.pk})
        self.assertEqual(set(actual.get_all_permissions()), {'catalog.view_activity'})


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DemoRoleWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()
        cls.organization = Organization.objects.get(pk=ROLE_PRACTICE_ID)
        cls.child = Child.objects.get(organization=cls.organization, code='Sami · fictif')
        cls.owner_child = Child.objects.get(organization=cls.organization, code='Maya · fictif')
        cls.legacy_child = Child.objects.get(code='Lina · fictif')

    def setUp(self):
        translation.activate('fr')

    @staticmethod
    def csrf(page):
        return html.unescape(re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1))

    def login(self, username, language='fr'):
        client = Client(enforce_csrf_checks=True)
        page = client.get(f'/{language}/login/')
        password = TEST_ENV[ROLE_PASSWORD_ENV[username]] if username in ROLE_PASSWORD_ENV else TEST_ENV['DEMO_PASSWORD']
        response = client.post(f'/{language}/login/', {'username': username, 'password': password, 'csrfmiddlewaretoken': self.csrf(page)})
        self.assertEqual(response.status_code, 302, username)
        self.assertIn('_auth_user_id', client.session, username)
        return client

    def test_all_profiles_have_real_form_logins_and_available_home(self):
        for username in (*LEGACY_DEMO_USERNAMES, *ROLE_USERNAMES):
            with self.subTest(username=username):
                client = self.login(username)
                response = client.get(reverse('dashboard'), follow=True)
                self.assertEqual(response.status_code, 200)
                if username in ['editorial', 'editeur', 'relecteur_clinique', 'relecteur_linguistique']:
                    self.assertEqual(response.redirect_chain[-1][0], reverse('editorial_index'))
                elif username == 'gestionnaire':
                    self.assertEqual(response.redirect_chain[-1][0], reverse('billing_index'))

    def test_role_capabilities_are_separate_and_scoped(self):
        expected = {'editeur': (True, False, False, True), 'relecteur_clinique': (False, True, False, False), 'relecteur_linguistique': (False, False, True, False)}
        for username in ROLE_USERNAMES:
            user = User.objects.get(username=username)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
        for username, capabilities in expected.items():
            grants = EditorialGrant.objects.filter(user__username=username)
            self.assertEqual(grants.count(), 3)
            self.assertEqual(set(grants.values_list('edit', 'clinical_review', 'linguistic_review', 'publish')), {capabilities})
        operator = User.objects.get(username='gestionnaire')
        self.assertEqual(operator.get_all_permissions(), {'core.manage_entitlements'})
        self.assertFalse(Membership.objects.filter(user=operator).exists())
        self.assertFalse(FamilyLink.objects.filter(user=operator).exists())
        self.assertFalse(EditorialGrant.objects.filter(user=operator).exists())

    def test_new_role_programs_use_guided_current_examples_without_replacing_legacy(self):
        programs = Program.objects.filter(organization=self.organization).prefetch_related('items__activity')
        self.assertEqual(programs.count(), 6)
        for program in programs:
            activity = program.items.get().activity
            self.assertEqual(activity.version, 2)
            self.assertTrue(activity.is_demo)
            self.assertEqual(activity.state, 'published')
            self.assertEqual(set(activity.practice_guide), {'fr', 'en', 'ar'})
            self.assertEqual(activity.variety_id, program.variety_id)
        self.assertEqual(self.legacy_child.programs.get().items.get().activity.version, 1)

    def test_reseeding_does_not_reset_credentials_records_or_revoked_affiliations(self):
        models = [User, Organization, Membership, Entitlement, Child, FamilyLink, Program, ProgramItem, EditorialGrant, Activity]
        counts = [model.objects.count() for model in models]
        passwords = dict(User.objects.values_list('username', 'password'))
        self.child.code = 'Sami renommé · fictif'
        self.child.age_years = 6
        self.child.save()
        existing_program = self.child.programs.get(variety__language='en')
        existing_program.title = 'Custom fictional title'
        existing_program.state = 'completed'
        existing_program.save()
        self.child.varieties.remove(existing_program.variety)
        withdrawn = self.child.programs.get(variety__language='ar').items.get().activity
        withdrawn.state = 'withdrawn'
        withdrawn.save()
        Membership.objects.filter(user__username='orthophoniste').update(active=False)
        FamilyLink.objects.filter(user__username='accompagnant').update(active=False)
        EditorialGrant.objects.filter(user__username='relecteur_clinique').update(clinical_review=False)
        entitlement = Entitlement.objects.get(organization=self.organization)
        entitlement.practitioner_quota = 1
        entitlement.save()
        changed = {key: value + '-changed' for key, value in TEST_ENV.items()}
        output = seed(env=changed)
        self.assertEqual([model.objects.count() for model in models], counts)
        self.assertEqual(dict(User.objects.values_list('username', 'password')), passwords)
        self.assertFalse(Membership.objects.get(user__username='orthophoniste').active)
        self.assertFalse(FamilyLink.objects.get(user__username='accompagnant').active)
        self.assertFalse(EditorialGrant.objects.filter(user__username='relecteur_clinique', clinical_review=True).exists())
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.practitioner_quota, 1)
        self.child.refresh_from_db()
        self.assertEqual(self.child.code, 'Sami renommé · fictif')
        self.assertEqual(self.child.age_years, 6)
        self.assertFalse(self.child.varieties.filter(pk=existing_program.variety_id).exists())
        existing_program.refresh_from_db()
        self.assertEqual(existing_program.title, 'Custom fictional title')
        self.assertEqual(existing_program.state, 'completed')
        withdrawn.refresh_from_db()
        self.assertEqual(withdrawn.state, 'withdrawn')
        for secret in changed.values():
            self.assertNotIn(secret, output)

    def test_owner_manages_practice_but_only_explicit_responsible_profiles(self):
        client = self.login('responsable')
        for name in ['members', 'subscription', 'organization_settings']:
            self.assertEqual(client.get(reverse(name)).status_code, 200)
        self.assertEqual(client.get(reverse('child_detail', args=[self.owner_child.pk])).status_code, 200)
        for child in [self.child, self.legacy_child]:
            self.assertEqual(client.get(reverse('child_detail', args=[child.pk])).status_code, 404)
            self.assertEqual(client.get(reverse('export_child', args=[child.pk])).status_code, 404)

    def test_clinician_uses_own_profile_and_cannot_manage_cabinet_or_other_profiles(self):
        client = self.login('orthophoniste')
        self.assertEqual(client.get(reverse('child_detail', args=[self.child.pk])).status_code, 200)
        self.assertEqual(client.get(reverse('program_create', args=[self.child.pk])).status_code, 200)
        for name in ['members', 'subscription', 'organization_settings']:
            self.assertEqual(client.get(reverse(name)).status_code, 404)
        for child in [self.owner_child, self.legacy_child]:
            self.assertEqual(client.get(reverse('child_detail', args=[child.pk])).status_code, 404)

    def test_accompanist_can_submit_assigned_three_varieties_without_clinician_rights(self):
        client = self.login('accompagnant')
        for language in ['fr', 'en', 'ar']:
            program = self.child.programs.get(variety__language=language)
            page = client.get(f'/{language}/programs/{program.pk}/')
            run = client.post(f'/{language}/programs/{program.pk}/start/', {'csrfmiddlewaretoken': self.csrf(page)}, follow=True)
            self.assertEqual(run.status_code, 200)
            exercise = client.get(run.context['resume_url'])
            ticket = exercise.context['form'].initial['ticket']
            answer = signing.loads(ticket, salt='practice')['target']
            saved = client.post(run.context['resume_url'], {'ticket': ticket, 'answer': answer, 'completion': 'completed', 'parent_report': 'help', 'comment': 'Fictional accompanist report', 'csrfmiddlewaretoken': self.csrf(exercise)}, follow=True)
            self.assertEqual(saved.status_code, 200)
            self.assertContains(saved, 'Fictional accompanist report')
        self.assertEqual(PracticeSession.objects.filter(user__username='accompagnant').count(), 3)
        forbidden = client.post(reverse('archive_child', args=[self.child.pk]), {'csrfmiddlewaretoken': self.csrf(page)})
        self.assertEqual(forbidden.status_code, 404)
        self.assertEqual(client.get(reverse('child_edit', args=[self.child.pk])).status_code, 404)
        self.assertEqual(client.get(reverse('child_detail', args=[self.legacy_child.pk])).status_code, 404)

    def test_clinician_feedback_is_shared_and_observation_stays_private(self):
        program = self.child.programs.get(variety__language='fr')
        clinician = self.login('orthophoniste')
        page = clinician.get(reverse('program_detail', args=[program.pk]))
        response = clinician.post(reverse('program_detail', args=[program.pk]), {'text': 'Private-role-fixture', 'csrfmiddlewaretoken': self.csrf(page)})
        self.assertEqual(response.status_code, 302)
        composer = clinician.get(reverse('family_feedback_create', args=[program.pk]))
        response = clinician.post(reverse('family_feedback_create', args=[program.pk]), {'text': 'Shared-role-fixture', 'csrfmiddlewaretoken': self.csrf(composer)})
        self.assertEqual(response.status_code, 302)
        family = self.login('accompagnant')
        family_page = family.get(reverse('program_detail', args=[program.pk]))
        self.assertContains(family_page, 'Shared-role-fixture')
        self.assertNotContains(family_page, 'Private-role-fixture')
        self.assertEqual(family.post(reverse('family_feedback_create', args=[program.pk]), {'text': 'Forbidden', 'csrfmiddlewaretoken': self.csrf(family_page)}).status_code, 404)
        self.assertEqual(Observation.objects.filter(program=program).count(), 1)

    def test_separate_reviewers_can_post_only_their_discipline_and_cannot_publish(self):
        activity = Activity.objects.get(series=uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-demo-role-review:fr-fr-pilot'), version=1)
        for username, allowed_kind, forbidden_kind in [('relecteur_clinique', 'clinical', 'linguistic'), ('relecteur_linguistique', 'linguistic', 'clinical')]:
            client = self.login(username)
            page = client.get(reverse('editorial_detail', args=[activity.pk]))
            response = client.post(reverse('editorial_detail', args=[activity.pk]), {'kind': allowed_kind, 'approved': True, 'note': 'Fictional review only', 'csrfmiddlewaretoken': self.csrf(page)})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(Review.objects.filter(activity=activity, reviewer__username=username, kind=allowed_kind).count(), 1)
            self.assertEqual(client.post(reverse('editorial_detail', args=[activity.pk]), {'kind': forbidden_kind, 'approved': True, 'note': 'Forbidden', 'csrfmiddlewaretoken': self.csrf(page)}).status_code, 403)
            self.assertEqual(client.post(reverse('editorial_transition', args=[activity.pk]), {'state': 'approved', 'csrfmiddlewaretoken': self.csrf(page)}).status_code, 403)
            self.assertEqual(client.post(reverse('editorial_clone', args=[activity.pk]), {'csrfmiddlewaretoken': self.csrf(page)}).status_code, 403)
            self.assertEqual(client.get(reverse('editorial_upload')).status_code, 403)
            self.assertEqual(client.get(reverse('child_detail', args=[self.child.pk])).status_code, 404)
        self.assertEqual(Review.objects.filter(activity=activity).count(), 2)

    def test_editor_can_clone_but_cannot_review_or_access_profiles(self):
        activity = Activity.objects.filter(is_demo=True, state='published', variety__code='fr-fr-pilot').first()
        client = self.login('editeur')
        page = client.get(reverse('editorial_detail', args=[activity.pk]))
        response = client.post(reverse('editorial_clone', args=[activity.pk]), {'csrfmiddlewaretoken': self.csrf(page)}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Activity.objects.filter(series=activity.series).count(), 2)
        self.assertEqual(client.post(reverse('editorial_detail', args=[activity.pk]), {'kind': 'clinical', 'approved': True, 'note': 'Forbidden', 'csrfmiddlewaretoken': self.csrf(page)}).status_code, 403)
        self.assertEqual(client.get(reverse('child_detail', args=[self.child.pk])).status_code, 404)

    def test_billing_manager_has_operational_ui_and_no_clinical_access(self):
        client = self.login('gestionnaire')
        index = client.get(reverse('billing_index'))
        self.assertContains(index, ROLE_PRACTICE_NAME)
        self.assertNotContains(index, self.child.code)
        detail = client.get(reverse('billing_detail', args=[self.organization.pk]))
        self.assertEqual(detail.status_code, 200)
        entitlement = Entitlement.objects.get(organization=self.organization)
        data = {'plan': 'Fictional manual plan', 'status': 'active', 'expires_at': entitlement.expires_at.strftime('%Y-%m-%d %H:%M:%S'), 'child_quota': 15, 'practitioner_quota': 5, 'amount': '0', 'currency': 'EUR', 'billing_reference': 'fictional-role-fixture', 'csrfmiddlewaretoken': self.csrf(detail)}
        self.assertEqual(client.post(reverse('billing_detail', args=[self.organization.pk]), data).status_code, 302)
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.billing_reference, 'fictional-role-fixture')
        program = self.child.programs.get(variety__language='fr')
        for name, pk in [('child_detail', self.child.pk), ('export_child', self.child.pk), ('program_detail', program.pk), ('family_feedback_create', program.pk)]:
            self.assertEqual(client.get(reverse(name, args=[pk])).status_code, 404)
        self.assertEqual(client.post(reverse('archive_child', args=[self.child.pk]), {'csrfmiddlewaretoken': self.csrf(detail)}).status_code, 404)
        self.assertEqual(client.get(reverse('editorial_index')).status_code, 404)

    @override_settings(MFA_REQUIRED=True)
    def test_privileged_role_profiles_still_require_mfa_in_real_security_mode(self):
        for name in ['responsable', 'orthophoniste', 'editeur', 'relecteur_clinique', 'relecteur_linguistique', 'gestionnaire']:
            self.client.force_login(User.objects.get(username=name))
            self.assertRedirects(self.client.get(reverse('dashboard')), reverse('mfa_setup'), fetch_redirect_response=False)