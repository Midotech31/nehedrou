"""A single account can be a professional and caregiver without losing either space."""
from datetime import timedelta
import secrets
import uuid

from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from care.models import Child, FamilyLink, Observation, Program, ProgramItem
from catalog.models import Activity, EditorialGrant, Variety
from core.testing import practice_form_data
from core.access import professional_children
from core.models import Entitlement, Invitation, Membership, Organization, User


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class HybridWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.professional = User.objects.create_user('hybrid-professional', 'hybrid-pro@example.test')
        cls.clinician = User.objects.create_user('hybrid-other-clinician', 'hybrid-clinician@example.test')
        cls.editor = User.objects.create_user('hybrid-editor', 'hybrid-editor@example.test')
        cls.operator = User.objects.create_user('hybrid-operator', 'hybrid-operator@example.test')
        cls.outsider = User.objects.create_user('hybrid-outsider', 'hybrid-outsider@example.test')
        cls.org_a = Organization.objects.create(name='Fictional own practice A')
        cls.org_b = Organization.objects.create(name='Fictional family practice B')
        cls.membership_a = Membership.objects.create(user=cls.professional, organization=cls.org_a, role='owner')
        cls.membership_b = Membership.objects.create(user=cls.clinician, organization=cls.org_b, role='owner')
        for org in (cls.org_a, cls.org_b):
            Entitlement.objects.create(organization=org, expires_at=timezone.now()+timedelta(days=10), practitioner_quota=5)
        cls.variety = Variety.objects.create(code='fr-fr-pilot', language='fr', label='French')
        EditorialGrant.objects.create(user=cls.editor, variety=cls.variety, edit=True)
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.own_child = Child.objects.create(organization=cls.org_a, responsible=cls.professional, code='Fictional professional dossier', age_years=5)
        cls.family_child = Child.objects.create(organization=cls.org_b, responsible=cls.clinician, code='Fictional family dossier · fictif', age_years=5)
        cls.unlinked_child = Child.objects.create(organization=cls.org_b, responsible=cls.clinician, code='Fictional unlinked dossier', age_years=5)
        for child in (cls.own_child, cls.family_child, cls.unlinked_child):
            child.varieties.add(cls.variety)
        cls.activity = Activity.objects.create(variety=cls.variety, series=uuid.uuid4(), title='Fictional game',
            contrast='Illustrative only', word_a='pomme', word_b='fourmi', image_a='editorial/arabic-apple.svg', image_b='editorial/ant.svg',
            instructions={'fr':'Exemple fictif.', 'en':'Fictional example.', 'ar':'مثال خيالي.'}, rights='Fictional fixture only.',
            population='Fictional data only.', limitations='Not clinical content.', state='published', is_demo=True)
        cls.own_program = Program.objects.create(organization=cls.org_a, child=cls.own_child, variety=cls.variety,
            created_by=cls.professional, title='Fictional professional program')
        cls.family_program = Program.objects.create(organization=cls.org_b, child=cls.family_child, variety=cls.variety,
            created_by=cls.clinician, title='Fictional family program')
        for program in (cls.own_program, cls.family_program):
            ProgramItem.objects.create(program=program, activity=cls.activity)
        Observation.objects.create(program=cls.family_program, author=cls.clinician, text='PRIVATE_OTHER_CLINICIAN_MARKER')

    def setUp(self):
        translation.activate('en')

    def accept(self, actor, kind='family', organization=None):
        org = organization or self.org_b
        invitation, token = Invitation.issue(org, self.family_child if kind=='family' else None,
            actor.email, self.clinician if org==self.org_b else self.professional, kind=kind)
        self.client.force_login(actor)
        response = self.client.post(reverse('invite', args=[token]))
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        return invitation

    def assert_family_lists(self):
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertTrue(dashboard.context['family_workspace'])
        self.assertIsNone(dashboard.context['current_membership'])
        self.assertEqual([program.pk for program in dashboard.context['programs']], [self.family_program.pk])
        self.assertNotContains(dashboard, self.own_child.code)
        self.assertNotContains(dashboard, self.unlinked_child.code)
        self.assertContains(dashboard, reverse('program_detail', args=[self.family_program.pk]))
        profiles = self.client.get(reverse('children'))
        self.assertEqual([child.pk for child in profiles.context['page']], [self.family_child.pk])
        self.assertNotContains(profiles, self.own_child.code)
        self.assertNotContains(profiles, self.unlinked_child.code)
        return dashboard

    def test_professional_family_invitation_opens_linked_family_program_and_switches_back(self):
        self.accept(self.professional)
        dashboard = self.assert_family_lists()
        self.assertContains(dashboard, 'id="workspace-select"')
        self.assertEqual(self.client.session['workspace'], 'family')
        self.assertEqual(Membership.objects.filter(user=self.professional).count(), 1)
        self.assertEqual(list(professional_children(self.professional).values_list('pk', flat=True)), [self.own_child.pk])
        detail = self.client.get(reverse('program_detail', args=[self.family_program.pk]))
        self.assertNotContains(detail, 'PRIVATE_OTHER_CLINICIAN_MARKER')
        self.assertEqual(self.client.post(reverse('program_detail', args=[self.family_program.pk]), {'text':'forbidden note'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('program_create', args=[self.family_child.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('members'), {'email':'new@example.test'}).status_code, 404)
        self.assertRedirects(self.client.post(reverse('switch_practice'), {'space':'professional'}), reverse('dashboard'))
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual([p.pk for p in dashboard.context['programs']], [self.own_program.pk])
        self.assertEqual(dashboard.context['current_membership'].pk, self.membership_a.pk)
        self.assertNotContains(dashboard, self.family_child.code)

    def test_editorial_and_platform_accounts_can_reach_family_and_return_to_their_role(self):
        for actor, destination in ((self.editor, 'editorial_index'), (self.operator, 'billing_index')):
            with self.subTest(role=destination):
                self.accept(actor)
                dashboard = self.assert_family_lists()
                self.assertContains(dashboard, reverse('children'))
                for destination_name in ('editorial_index', 'followup:definition_list', 'qualification:index', 'operations_diagnostics', 'billing_index'):
                    self.assertNotContains(dashboard, 'href="' + reverse(destination_name) + '"')
                self.assertFalse(professional_children(actor).exists())
                self.assertFalse(Membership.objects.filter(user=actor).exists())
                self.assertRedirects(self.client.post(reverse('switch_practice'), {'space':'professional'}),
                    reverse('dashboard'), fetch_redirect_response=False)
                self.assertRedirects(self.client.get(reverse('dashboard')), reverse(destination), fetch_redirect_response=False)
                role_page = self.client.get(reverse(destination))
                self.assertContains(role_page, 'id="workspace-select"')
                self.assertContains(role_page, 'href="' + reverse(destination) + '"')
                if actor == self.editor:
                    self.assertContains(role_page, 'href="' + reverse('followup:definition_list') + '"')
                    self.assertContains(role_page, 'href="' + reverse('qualification:index') + '"')
                else:
                    self.assertContains(role_page, 'href="' + reverse('operations_diagnostics') + '"')
                self.assertRedirects(self.client.post(reverse('switch_practice'), {'space':'family'}), reverse('dashboard'), fetch_redirect_response=False)
                self.assert_family_lists()

    def test_new_family_signup_selects_family_space_without_membership(self):
        invitation, token = Invitation.issue(self.org_b, self.family_child, 'new-hybrid-family@example.test', self.clinician)
        password = secrets.token_urlsafe(24)
        response = self.client.post(reverse('invite', args=[token]), {
            'username':'new-hybrid-family', 'instruction_language':'ar',
            'password1':password, 'password2':password})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        actor = User.objects.get(username='new-hybrid-family')
        self.assertFalse(Membership.objects.filter(user=actor).exists())
        self.assertEqual(self.client.session['workspace'], 'family')
        self.assert_family_lists()
    def test_professional_invitation_selects_its_actual_cabinet_from_family_space(self):
        FamilyLink.objects.create(user=self.professional, child=self.family_child)
        self.client.force_login(self.professional)
        self.client.post(reverse('switch_practice'), {'space':'family'})
        self.accept(self.professional, kind='clinician')
        self.assertEqual(self.client.session['workspace'], 'professional')
        self.assertEqual(self.client.session['organization'], str(self.org_b.pk))
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.context['current_membership'].organization_id, self.org_b.pk)
        self.assertNotContains(dashboard, self.own_child.code)
        self.assertNotContains(dashboard, self.family_child.code)
        self.assertEqual(dashboard.context['children_count'], 0)
        self.assertFalse(professional_children(self.professional).filter(pk=self.family_child.pk).exists())

    def test_legacy_membership_post_restores_professional_space_and_is_scoped(self):
        self.accept(self.professional)
        response = self.client.post(reverse('switch_practice'), {'membership':str(self.membership_a.pk)})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['workspace'], 'professional')
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        self.assertEqual(self.client.post(reverse('switch_practice'), {'membership':str(self.membership_b.pk)}).status_code, 404)
        self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'unknown'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('switch_practice')).status_code, 405)

    def test_workspace_selection_requires_actual_role_and_active_family_link(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'family'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'professional'}).status_code, 404)
        FamilyLink.objects.create(user=self.outsider, child=self.family_child, active=False)
        self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'family'}).status_code, 404)
        self.assertEqual(Membership.objects.filter(user=self.outsider).count(), 0)

    def test_all_revoked_links_empty_family_space_but_keep_way_back_to_professional(self):
        self.accept(self.professional)
        link = FamilyLink.objects.get(user=self.professional, child=self.family_child)
        link.active = False
        link.save()
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['children_count'], 0)
        self.assertEqual(dashboard.context['program_count'], 0)
        self.assertContains(dashboard, 'id="workspace-select"')
        self.assertNotContains(dashboard, self.own_child.code)
        self.assertEqual(self.client.get(reverse('child_detail', args=[self.family_child.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('program_detail', args=[self.family_program.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'family'}).status_code, 404)
        self.assertRedirects(self.client.post(reverse('switch_practice'), {'space':'professional'}), reverse('dashboard'))
        self.assertContains(self.client.get(reverse('dashboard')), self.own_child.code)

    def test_family_lists_include_links_in_multiple_cabinets_but_not_professional_only_records(self):
        self.accept(self.professional)
        family_c = Child.objects.create(organization=self.org_a, responsible=self.professional, code='Explicitly linked second family dossier', age_years=5)
        family_c.varieties.add(self.variety)
        FamilyLink.objects.create(user=self.professional, child=family_c)
        profiles = self.client.get(reverse('children'))
        self.assertEqual(set(child.pk for child in profiles.context['page']), {self.family_child.pk, family_c.pk})
        self.assertNotContains(profiles, self.own_child.code)
        self.assertNotContains(profiles, self.unlinked_child.code)

    def test_existing_hybrid_accounts_can_choose_family_without_reaccepting_invitation(self):
        FamilyLink.objects.create(user=self.editor, child=self.family_child)
        self.client.force_login(self.editor)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('editorial_index'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('editorial_index')), 'id="workspace-select"')
        self.assertRedirects(self.client.post(reverse('switch_practice'), {'space':'family'}), reverse('dashboard'), fetch_redirect_response=False)
        self.assert_family_lists()

    def test_switch_is_csrf_protected(self):
        FamilyLink.objects.create(user=self.professional, child=self.family_child)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.professional)
        self.assertEqual(client.post(reverse('switch_practice'), {'space':'family'}).status_code, 403)
        self.assertNotIn('workspace', client.session)

    def test_selector_and_auto_selection_work_in_all_interface_languages(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                self.accept(self.professional)
                page = self.assert_family_lists()
                self.assertContains(page, 'name="space"')
                self.assertContains(page, 'value="family" selected')
                self.assertContains(page, 'value="professional"')
                self.assertContains(page, 'lang="'+language+'"')

    @override_settings(MFA_REQUIRED=True)
    def test_family_choice_does_not_bypass_actual_professional_editorial_or_platform_mfa(self):
        for actor in (self.professional, self.editor, self.operator):
            with self.subTest(actor=actor.username):
                FamilyLink.objects.create(user=actor, child=self.family_child)
                self.client.force_login(actor)
                session = self.client.session
                session['workspace'] = 'family'
                session.save()
                self.assertRedirects(self.client.get(reverse('dashboard')), reverse('mfa_setup'), fetch_redirect_response=False)
    def family_followup_fixture(self):
        from types import SimpleNamespace
        from followup.tests import definition, goal, start, rating
        from followup.models import ParentCoaching
        from followup.services import save_rating, finalize_administration, share_summary
        fixture = SimpleNamespace(pro=self.clinician, child=self.family_child, variety=self.variety, organization=self.org_b)
        protocol = definition(fixture, 2)
        objective = goal(fixture, protocol)
        administration = start(fixture, protocol, objective)
        for item in protocol.items:
            save_rating(self.clinician, administration, item['id'], rating())
        administration = finalize_administration(self.clinician, administration)
        share_summary(self.clinician, administration, 'Shared family B safe summary')
        shared = ParentCoaching.objects.create(organization=self.org_b, child=self.family_child,
            author=self.clinician, variety=self.variety, instruction_language='en',
            instructions='Shared family B instructions', clinician_note='PRIVATE_COACHING_B_MARKER')
        private = ParentCoaching.objects.create(organization=self.org_a, child=self.own_child,
            author=self.professional, variety=self.variety, instruction_language='en',
            instructions='PROFESSIONAL_A_COACHING_MARKER', clinician_note='PRIVATE_COACHING_A_MARKER')
        return administration, shared, private, protocol

    def test_hybrid_family_followup_lists_only_linked_coaching_and_shared_summaries(self):
        administration, shared, private, protocol = self.family_followup_fixture()
        for actor in (self.professional, self.editor, self.operator):
            with self.subTest(actor=actor.username):
                self.accept(actor)
                page = self.client.get(reverse('followup:index'))
                self.assertEqual(page.status_code, 200)
                self.assertFalse(page.context['professional'])
                self.assertEqual([row.pk for row in page.context['coaching']], [shared.pk])
                self.assertEqual([row.pk for row in page.context['shares']], [administration.pk])
                self.assertContains(page, reverse('followup:coaching_detail', args=[shared.pk]))
                self.assertNotContains(page, self.own_child.code)
                self.assertNotContains(page, self.unlinked_child.code)
                self.assertNotContains(page, 'PROFESSIONAL_A_COACHING_MARKER')
                self.assertNotContains(page, 'PRIVATE_COACHING_B_MARKER')
                for item in protocol.items:
                    self.assertNotContains(page, item['word'])
                detail = self.client.get(reverse('followup:coaching_detail', args=[shared.pk]))
                self.assertContains(detail, 'Shared family B instructions')
                self.assertNotContains(detail, 'PRIVATE_COACHING_B_MARKER')
                summary = self.client.get(reverse('followup:family_summary', args=[administration.pk]))
                self.assertContains(summary, 'Shared family B safe summary')
                for item in protocol.items:
                    self.assertNotContains(summary, item['word'])
                self.assertEqual(self.client.get(reverse('followup:report', args=[administration.pk])).status_code, 404)
                self.assertEqual(self.client.get(reverse('followup:administration_detail', args=[administration.pk])).status_code, 404)

    def test_revocation_rechecks_family_followup_without_falling_back_to_professional_dossiers(self):
        administration, shared, private, protocol = self.family_followup_fixture()
        self.accept(self.professional)
        link = FamilyLink.objects.get(child=self.family_child, user=self.professional)
        link.active = False
        link.save()
        page = self.client.get(reverse('followup:index'))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['professional'])
        self.assertEqual(list(page.context['shares']), [])
        self.assertEqual(page.context['coaching'], [])
        self.assertNotContains(page, self.own_child.code)
        self.assertEqual(self.client.get(reverse('followup:coaching_detail', args=[shared.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('followup:family_summary', args=[administration.pk])).status_code, 404)
    def test_retired_last_role_does_not_hide_still_authorized_family_programs(self):
        retired_member = User.objects.create_user('hybrid-retired-clinician', 'hybrid-retired@example.test')
        membership = Membership.objects.create(user=retired_member, organization=self.org_a, role='clinician')
        for actor, retired_kind in ((retired_member, 'membership'), (self.editor, 'editorial'), (self.operator, 'platform')):
            with self.subTest(retired_kind=retired_kind):
                self.accept(actor)
                self.assertRedirects(self.client.post(reverse('switch_practice'), {'space':'professional'}),
                    reverse('dashboard'), fetch_redirect_response=False)
                self.assertEqual(self.client.session['workspace'], 'professional')
                if retired_kind == 'membership':
                    membership.active = False
                    membership.save()
                elif retired_kind == 'editorial':
                    EditorialGrant.objects.filter(user=actor).delete()
                else:
                    actor.user_permissions.clear()
                dashboard = self.assert_family_lists()
                self.assertFalse(dashboard.context['has_professional_space'])
                self.assertFalse(dashboard.context['show_workspace_switch'])
                self.assertFalse(professional_children(actor).exists())
                self.assertEqual(self.client.get(reverse('editorial_index')).status_code, 404)
                self.assertEqual(self.client.get(reverse('operations_diagnostics')).status_code, 403)
                self.assertEqual(self.client.get(reverse('child_create')).status_code, 404)
                self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'professional'}).status_code, 404)
    def test_revoked_selected_membership_falls_back_to_another_active_own_cabinet(self):
        from core.services import revoke_membership
        old = Membership.objects.create(user=self.outsider, organization=self.org_a, role='clinician')
        remaining = Membership.objects.create(user=self.outsider, organization=self.org_b, role='clinician')
        child = Child.objects.create(organization=self.org_b, responsible=self.outsider,
            code='Remaining professional dossier · fictif', age_years=5)
        child.varieties.add(self.variety)
        program = Program.objects.create(organization=self.org_b, child=child, variety=self.variety,
            created_by=self.outsider, title='Remaining professional program')
        ProgramItem.objects.create(program=program, activity=self.activity)
        self.client.force_login(self.outsider)
        self.client.post(reverse('switch_practice'), {'membership':str(old.pk)})
        revoke_membership(self.professional, self.org_a, old.pk)
        old.refresh_from_db()
        self.assertFalse(old.active)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['current_membership'].pk, remaining.pk)
        self.assertEqual([row.pk for row in dashboard.context['programs']], [program.pk])
        self.assertContains(dashboard, self.org_b.name)
        self.assertContains(dashboard, child.code)
        self.assertNotContains(dashboard, self.own_child.code)
        self.assertNotContains(dashboard, self.family_child.code)
        self.assertEqual(self.client.get(reverse('child_detail', args=[self.own_child.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('switch_practice'), {'membership':str(old.pk)}).status_code, 404)
        FamilyLink.objects.create(user=self.outsider, child=self.family_child)
        self.client.post(reverse('switch_practice'), {'space':'family'})
        self.assert_family_lists()
        self.assertTrue(Membership.objects.get(pk=remaining.pk).active)
        self.assertFalse(Membership.objects.get(pk=old.pk).active)

    def test_malformed_or_foreign_cabinet_selection_never_crashes_or_selects_another_users_role(self):
        self.client.force_login(self.professional)
        for selected in ('not-a-uuid', {'invalid':'value'}, str(uuid.uuid4()), str(self.org_b.pk), None):
            with self.subTest(selected=selected):
                session = self.client.session
                session['workspace'] = 'professional'
                session['organization'] = selected
                session.save()
                page = self.client.get(reverse('dashboard'))
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context['current_membership'].pk, self.membership_a.pk)
                self.assertEqual([row.pk for row in page.context['programs']], [self.own_program.pk])
                self.assertNotContains(page, self.family_child.code)
                self.assertEqual(self.client.session['organization'], selected)
                before = Child.objects.count()
                payload = {'code':'Invalid-selection POST', 'age_years':5, 'varieties':[str(self.variety.pk)]}
                self.assertEqual(self.client.post(reverse('child_create'), payload).status_code, 404)
                self.assertEqual(Child.objects.count(), before)
        FamilyLink.objects.create(user=self.professional, child=self.family_child)
        session = self.client.session
        session['workspace'] = 'family'
        session['organization'] = 'not-a-uuid'
        session.save()
        self.assert_family_lists()
    def test_stale_child_form_cannot_create_in_read_fallback_until_active_cabinet_is_selected(self):
        from core.services import revoke_membership
        old = Membership.objects.create(user=self.outsider, organization=self.org_a, role='clinician')
        active = Membership.objects.create(user=self.outsider, organization=self.org_b, role='clinician')
        self.client.force_login(self.outsider)
        self.client.post(reverse('switch_practice'), {'membership':str(old.pk)})
        form = self.client.get(reverse('child_create'))
        self.assertEqual(form.status_code, 200)
        self.assertEqual(form.context['current_membership'].pk, old.pk)
        payload = {'practice_scope': form.context['practice_scope'], 'code':'Fresh profile from retained form', 'age_years':5, 'varieties':[str(self.variety.pk)], 'demo_data_ack':'on'}
        revoke_membership(self.professional, self.org_a, old.pk)
        before = set(Child.objects.values_list('pk', flat=True))
        recovered = self.client.get(reverse('dashboard'))
        self.assertEqual(recovered.context['current_membership'].pk, active.pk)
        self.assertTrue(recovered.context['practice_selection_required'])
        self.assertContains(recovered, 'id="practice-select"')
        self.assertContains(recovered, 'Choose an active practice before saving changes.')
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        # Loading the new form also must not silently turn the stale A POST into B.
        self.assertEqual(self.client.get(reverse('child_create')).status_code, 200)
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        self.assertEqual(self.client.post(reverse('child_create'), payload).status_code, 404)
        self.assertEqual(set(Child.objects.values_list('pk', flat=True)), before)
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        self.assertRedirects(self.client.post(reverse('switch_practice'), {'membership':str(active.pk)}),
            reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['organization'], str(self.org_b.pk))
        form_b = self.client.get(reverse('child_create'))
        self.assertFalse(form_b.context['practice_selection_required'])
        self.assertEqual(form_b.context['current_membership'].pk, active.pk)
        payload['practice_scope'] = form_b.context['practice_scope']
        self.assertRedirects(self.client.post(reverse('child_create'), payload),
            reverse('child_detail', args=[Child.objects.get(code=payload['code']).pk]), fetch_redirect_response=False)
        created = Child.objects.get(code=payload['code'])
        self.assertEqual(created.organization_id, self.org_b.pk)
        self.assertEqual(created.responsible_id, self.outsider.pk)
        self.assertEqual(Child.objects.filter(organization=self.org_a).count(), 1)
        self.assertFalse(Membership.objects.get(pk=old.pk).active)

    def test_stale_owner_form_and_retry_never_create_or_rotate_under_fallback_cabinet(self):
        from unittest.mock import patch
        old = Membership.objects.create(user=self.outsider, organization=self.org_a, role='owner')
        active = Membership.objects.create(user=self.outsider, organization=self.org_b, role='owner')
        invite_a, _token_a = Invitation.issue(self.org_a, None, 'pending-a@example.test', self.outsider, kind='clinician')
        invite_b, _token_b = Invitation.issue(self.org_b, None, 'pending-b@example.test', self.outsider, kind='clinician')
        invite_b.delivery = 'failed'
        invite_b.save()
        original = {row.pk:(row.token_hash,row.revoked,row.used_at) for row in (invite_a,invite_b)}
        self.client.force_login(self.outsider)
        self.client.post(reverse('switch_practice'), {'membership':str(old.pk)})
        self.assertEqual(self.client.get(reverse('members')).status_code, 200)
        # Explicit operator role withdrawal; the public owner-revoke action stays forbidden.
        old.active = False
        old.save()
        before = set(Invitation.objects.values_list('pk', flat=True))
        preview_b = self.client.get(reverse('members'))
        self.assertEqual(preview_b.status_code, 200)
        self.assertEqual(preview_b.context['current_membership'].pk, active.pk)
        self.assertContains(preview_b, 'id="practice-select"')
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        with patch('django.core.mail.send_mail', return_value=1) as send:
            self.assertEqual(self.client.post(reverse('members'), {'email':'new-b@example.test'}).status_code, 404)
            for invitation in (invite_a, invite_b):
                self.assertEqual(self.client.post(reverse('resend_invitation', args=[invitation.pk])).status_code, 404)
            send.assert_not_called()
        self.assertEqual(set(Invitation.objects.values_list('pk', flat=True)), before)
        for invitation in (invite_a, invite_b):
            invitation.refresh_from_db()
            self.assertEqual((invitation.token_hash,invitation.revoked,invitation.used_at), original[invitation.pk])
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        self.client.post(reverse('switch_practice'), {'membership':str(active.pk)})
        self.assertEqual(self.client.session['organization'], str(self.org_b.pk))
        self.assertEqual(self.client.get(reverse('members')).context['current_membership'].pk, active.pk)
        with patch('django.core.mail.send_mail', return_value=1) as send:
            self.assertRedirects(self.client.post(reverse('members'), practice_form_data(self.client, reverse('members'), {'email':'new-b@example.test'})),
                reverse('members'), fetch_redirect_response=False)
            self.assertRedirects(self.client.post(reverse('resend_invitation', args=[invite_b.pk])),
                reverse('members'), fetch_redirect_response=False)
            self.assertEqual(send.call_count, 2)
        self.assertEqual(Invitation.objects.get(email='new-b@example.test').organization_id, self.org_b.pk)
        invite_b.refresh_from_db()
        self.assertTrue(invite_b.revoked)
        replacement = Invitation.objects.get(email=invite_b.email, revoked=False)
        self.assertEqual(replacement.organization_id, self.org_b.pk)
        self.assertNotEqual(replacement.token_hash, invite_b.token_hash)
        invite_a.refresh_from_db()
        self.assertEqual((invite_a.token_hash,invite_a.revoked,invite_a.used_at), original[invite_a.pk])
        self.assertFalse(Membership.objects.get(pk=old.pk).active)

    def test_first_session_requires_actual_form_context_for_single_role_creation(self):
        self.client.force_login(self.professional)
        self.assertNotIn('organization', self.client.session)
        direct = Client()
        direct.force_login(self.professional)
        direct_payload = {'code':'Direct first-session profile', 'age_years':5, 'varieties':[str(self.variety.pk)]}
        self.assertEqual(direct.post(reverse('child_create'), direct_payload).status_code, 409)
        self.assertFalse(Child.objects.filter(code=direct_payload['code']).exists())
        self.assertEqual(self.client.get(reverse('child_create')).status_code, 200)
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        payload = {'code':'First-session new profile', 'age_years':5, 'varieties':[str(self.variety.pk)]}
        self.assertRedirects(self.client.post(reverse('child_create'), practice_form_data(self.client, reverse('child_create'), payload)),
            reverse('child_detail', args=[Child.objects.get(code=payload['code']).pk]), fetch_redirect_response=False)
        self.assertEqual(Child.objects.get(code=payload['code']).organization_id, self.org_a.pk)
    def test_first_displayed_cabinet_is_bound_before_its_membership_can_be_revoked(self):
        from uuid import UUID
        from core.services import revoke_membership
        old = Membership.objects.create(pk=UUID(int=1), user=self.outsider, organization=self.org_a, role='clinician')
        active = Membership.objects.create(pk=UUID(int=2), user=self.outsider, organization=self.org_b, role='clinician')
        self.client.force_login(self.outsider)
        self.assertNotIn('organization', self.client.session)
        form_a = self.client.get(reverse('child_create'))
        self.assertEqual(form_a.context['current_membership'].pk, old.pk)
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        revoke_membership(self.professional, self.org_a, old.pk)
        payload = {'practice_scope': form_a.context['practice_scope'], 'code':'Initially displayed then revoked form', 'age_years':5, 'varieties':[str(self.variety.pk)]}
        before = set(Child.objects.values_list('pk', flat=True))
        self.assertEqual(self.client.post(reverse('child_create'), payload).status_code, 404)
        recovered = self.client.get(reverse('child_create'))
        self.assertEqual(recovered.context['current_membership'].pk, active.pk)
        self.assertTrue(recovered.context['practice_selection_required'])
        self.assertContains(recovered, 'id="practice-select"')
        self.assertEqual(self.client.session['organization'], str(self.org_a.pk))
        self.assertEqual(self.client.post(reverse('child_create'), payload).status_code, 404)
        self.assertEqual(set(Child.objects.values_list('pk', flat=True)), before)
        self.client.post(reverse('switch_practice'), {'membership':str(active.pk)})
        self.assertEqual(self.client.session['organization'], str(self.org_b.pk))
        self.assertFalse(self.client.get(reverse('child_create')).context['practice_selection_required'])
        self.assertEqual(self.client.post(reverse('child_create'), practice_form_data(self.client, reverse('child_create'), payload)).status_code, 302)
        self.assertEqual(Child.objects.get(code=payload['code']).organization_id, self.org_b.pk)