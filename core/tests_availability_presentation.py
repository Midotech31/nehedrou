"""Availability after publication, using fictional local software fixtures only."""
import io
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from care.models import Child, FamilyLink, Program
from catalog.content_catalog import current_catalog
from catalog.integrity import integrity_scope, invalidate_integrity, prepare_activities
from catalog.models import Activity, EditorialGrant, Variety
from catalog.presentation_availability import prepare_availability
from catalog.readiness import referenced_asset
from catalog.services import clone_version, transition
from qualification.opening import revoke_decision
from qualification.test_support import prepare_activity_fixture, availability_fixture
from .access import CURRENT_NOTICE_VERSION
from .forms import ProgramForm
from .models import AuditEvent, Entitlement, Membership, NoticeAcknowledgement, Organization, User
from .services import create_program


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PUBLIC_ORIGIN='https://fictional.example',
    OFFERED_CONTENT_VARIETIES=('ar-msa-pilot',),
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AvailabilityPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(
            code='ar-msa-pilot', language='ar', label='Synthetic standard-Arabic fixture')
        cls.other_variety = Variety.objects.create(
            code='ar-dz-pilot', language='ar', label='Synthetic Darja fixture')
        cls.pro = User.objects.create_user('availability-pro', 'pro@availability.example.test')
        cls.linguist = User.objects.create_user('availability-linguist', 'linguist@availability.example.test')
        cls.family = User.objects.create_user('availability-family', 'family@availability.example.test')
        cls.foreign = User.objects.create_user('availability-foreign', 'foreign@availability.example.test')
        cls.org = Organization.objects.create(name='Fictional availability practice')
        Membership.objects.create(organization=cls.org, user=cls.pro, role='owner')
        Entitlement.objects.create(organization=cls.org, expires_at=timezone.now()+timedelta(days=30),
            child_quota=5, practitioner_quota=5)
        cls.child = Child.objects.create(code='Availability fixture, not a patient', age_years=5,
            organization=cls.org, responsible=cls.pro)
        cls.child.varieties.add(cls.variety, cls.other_variety)
        FamilyLink.objects.create(child=cls.child, user=cls.family)
        cls.activity = Activity.objects.create(variety=cls.variety, series=uuid.uuid4(),
            title='Z fictional qualified software fixture', word_a='pa', word_b='ba', contrast='p/b',
            instructions={'en':'Fictional historical instructions', 'fr':'Consignes fictives', 'ar':'تعليمات وهمية'},
            population='Fictional software fixture', limitations='No clinical authorization',
            rights='Fictional regression rights only', is_demo=False)
        # Existing isolated fixture helpers exercise the real checks with synthetic
        # bytes and explicit fictional decisions. No deployment imports this module.
        prepare_activity_fixture(cls.activity, cls.pro, cls.linguist)
        transition(cls.pro, cls.activity.pk, 'approved')
        cls.activity = transition(cls.pro, cls.activity.pk, 'published')
        cls.decision = availability_fixture('practice', cls.variety, cls.activity.fingerprint(), cls.pro)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.pro)

    def values(self, activities=None):
        activities = activities or [self.activity]
        return {'title':'Fictional new program', 'variety':str(self.variety.pk),
            'activities':[str(activity.pk) for activity in activities],
            'guidance':'Fictional guidance', 'schedule':'Fictional schedule'}

    def program(self):
        return create_program(self.pro, self.child, {**self.values(), 'variety':self.variety,
            'activities':[self.activity]})

    def revoke_rights(self):
        asset = referenced_asset(self.activity.audio_a, 'audio')
        proof = asset.rights_evidence
        proof.revoked = True
        proof.revocation_reason = 'Fictional post-start rights withdrawal'
        proof.save()

    def library(self, **filters):
        return self.client.get(reverse('library'), filters)

    def assert_unavailable_card(self, response, activity=None):
        activity = activity or self.activity
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-unavailable-activity="{activity.pk}"')
        self.assertNotContains(response, reverse('activity_detail', args=[activity.pk]))
        if activity.audio_a:
            self.assertNotContains(response, activity.audio_a)
        self.assertNotContains(response, 'Audio available')

    def legacy_publication(self, title, *, variety=None, series=None, version=1, **fields):
        obj = Activity.objects.create(variety=variety or self.variety, series=series or uuid.uuid4(),
            version=version, title=title, contrast='Fictional legacy input', word_a='old-a', word_b='old-b',
            instructions={'en':'Fictional legacy instructions'}, is_demo=False, **fields)
        # Represent already-stored incomplete legacy publication, not an approval
        # or a supported publication path. The request must not repair/promote it.
        Activity.objects.filter(pk=obj.pk).update(state='published')
        obj.refresh_from_db()
        return obj

    def test_ready_content_is_linked_and_real_audio_badge_uses_the_actual_gate(self):
        self.assertTrue(self.activity.usable)
        before = AuditEvent.objects.count()
        response = self.library()
        self.assertEqual(response.context['result_count'], 1)
        self.assertEqual(response.context['available_on_page'], 1)
        self.assertEqual(response.context['unavailable_on_page'], 0)
        self.assertContains(response, reverse('activity_detail', args=[self.activity.pk]))
        self.assertContains(response, 'Audio available')
        self.assertEqual(self.client.get(reverse('activity_detail', args=[self.activity.pk])).status_code, 200)
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_demo_revision_cannot_replace_the_qualified_production_assignment(self):
        demo = clone_version(self.pro, self.activity)
        demo.title = 'Fictional demo-only revision'
        demo.is_demo = True
        demo.save()
        for state in ('review', 'approved', 'published'):
            demo = transition(self.pro, demo.pk, state)

        self.assertTrue(self.activity.usable)
        self.assertEqual(list(current_catalog(Activity.objects.filter(
            series=demo.series, state='published'))), [demo])
        response = self.client.get(reverse('library'),
            {'content_language': 'ar', 'variety': self.variety.code}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result_count'], 1)
        self.assertContains(response, reverse('activity_detail', args=[self.activity.pk]))
        self.assertNotContains(response, demo.title)
        self.assertEqual(next(row['count'] for row in response.context['arabic_collections']
            if row['code'] == self.variety.code), 1)
        response = self.client.get(reverse('editorial_detail', args=[self.activity.pk]), secure=True)
        self.assertFalse(response.context['is_latest_version'])

        NoticeAcknowledgement.objects.create(user=self.pro, organization=self.org,
            version=CURRENT_NOTICE_VERSION, language='en')
        assignment = reverse('program_create', args=[self.child.pk])
        response = self.client.get(assignment, secure=True)
        self.assertEqual(list(response.context['form'].fields['activities'].queryset), [self.activity])
        response = self.client.post(assignment, {**self.values(), 'action': 'assign'}, secure=True)
        program = Program.objects.get(title=self.values()['title'])
        self.assertRedirects(response, reverse('program_detail', args=[program.pk]), fetch_redirect_response=False)
        item = program.items.get()
        self.assertEqual(item.activity_id, self.activity.pk)
        self.client.force_login(self.family)
        with translation.override('ar'):
            response = self.client.get(reverse('practice', args=[item.pk]), secure=True)
            self.assertContains(response, self.activity.title)

        output = io.StringIO()
        call_command('check_readiness', json=True, stdout=output)
        self.assertEqual(json.loads(output.getvalue())['current_available_nondemo_counts_by_variety'],
            {self.variety.code: 1})

    def test_post_start_rights_revocation_updates_catalogue_form_and_launch_count(self):
        self.assertTrue(self.activity.usable)
        self.assertEqual(self.library().context['available_on_page'], 1)
        self.revoke_rights()
        self.assertFalse(self.activity.usable)
        response = self.library()
        self.assert_unavailable_card(response)
        self.assertEqual(response.context['result_count'], 1)
        self.assertEqual(response.context['available_on_page'], 0)
        self.assertEqual(response.context['unavailable_on_page'], 1)
        self.assertEqual(self.client.get(reverse('activity_detail', args=[self.activity.pk])).status_code, 404)
        form = ProgramForm(self.values(), child=self.child)
        self.assertFalse(form.is_valid())
        self.assertIn('activities', form.errors)
        output = io.StringIO()
        call_command('check_readiness', json=True, stdout=output)
        self.assertEqual(json.loads(output.getvalue())['current_available_nondemo_counts_by_variety'],
            {'ar-msa-pilot':0})
        with self.assertRaises(ValidationError):
            create_program(self.pro, self.child, {**self.values(), 'variety':self.variety,
                'activities':[self.activity]})
        self.assertEqual(Program.objects.count(), 0)

    def test_post_start_authorised_availability_revocation_is_rechecked_next_request(self):
        self.assertEqual(self.library().context['available_on_page'], 1)
        revoke_decision(self.pro, self.decision.pk, 'Fictional availability withdrawal')
        self.assertFalse(self.activity.usable)
        self.assert_unavailable_card(self.library())
        self.assertFalse(ProgramForm(self.values(), child=self.child).is_valid())

    def test_post_start_reviewer_permission_withdrawal_is_rechecked(self):
        self.assertEqual(self.library().context['available_on_page'], 1)
        grant = EditorialGrant.objects.get(user=self.linguist, variety=self.variety)
        grant.linguistic_review = False
        grant.save()
        self.assertFalse(self.activity.usable)
        self.assert_unavailable_card(self.library())
        self.assertFalse(ProgramForm(self.values(), child=self.child).is_valid())

    def test_changed_exact_media_bytes_remove_availability_without_changing_the_reference(self):
        asset = referenced_asset(self.activity.audio_a, 'audio')
        with asset.file.storage.open(asset.file.name, 'rb') as file:
            original = file.read()
        try:
            with asset.file.storage.open(asset.file.name, 'wb') as file:
                file.write(b'Fictional corrupted bytes')
            self.assertFalse(self.activity.usable)
            self.assert_unavailable_card(self.library())
            self.assertFalse(ProgramForm(self.values(), child=self.child).is_valid())
        finally:
            with asset.file.storage.open(asset.file.name, 'wb') as file:
                file.write(original)

    def test_assigned_history_remains_readable_only_in_its_existing_scope_without_media(self):
        program = self.program()
        self.revoke_rights()
        for actor in (self.pro, self.family):
            self.client.force_login(actor)
            response = self.client.get(reverse('activity_detail', args=[self.activity.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['assigned_history'])
            self.assertFalse(response.context['activity_available'])
            self.assertContains(response, 'Assigned historical content')
            self.assertNotContains(response, self.activity.audio_a)
            self.assertNotContains(response, 'activity-pair')
            self.assertEqual(self.client.get(reverse('program_detail', args=[program.pk])).status_code, 200)
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(reverse('activity_detail', args=[self.activity.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('program_detail', args=[program.pk])).status_code, 404)
        self.client.force_login(self.pro)
        self.assertEqual(self.client.get(reverse('editorial_detail', args=[self.activity.pk])).status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.items.get().activity_id, self.activity.pk)

    def test_bound_preview_rejects_unavailable_selection_without_program_creation(self):
        self.revoke_rights()
        response = self.client.post(reverse('program_create', args=[self.child.pk]),
            {**self.values(), 'action':'preview'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('activities', response.context['form'].errors)
        self.assertIsNone(response.context['preview'])
        self.assertEqual(Program.objects.count(), 0)

    def test_unbound_form_explains_later_verification_without_scanning_media(self):
        for index in range(20):
            self.legacy_publication(f'Fictional unbound choice {index:02d}')
        with patch('qualification.models.digest_file', side_effect=AssertionError('Unbounded GET byte scan')):
            form = ProgramForm(child=self.child)
            self.assertEqual(form.fields['activities'].queryset.count(), 21)
            response = self.client.get(reverse('program_create', args=[self.child.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Availability is checked when you preview or save this program.')

    def test_builder_shows_simple_instructions_in_the_selected_language(self):
        self.legacy_publication('Fictional alternative with English instructions only')
        route = reverse('program_create', args=[self.child.pk])
        for language, direction, wording in [
            ('fr', 'ltr', 'Consignes fictives'),
            ('en', 'ltr', 'Fictional historical instructions'),
            ('ar', 'rtl', 'تعليمات وهمية'),
        ]:
            with self.subTest(language=language):
                User.objects.filter(pk=self.pro.pk).update(instruction_language=language)
                response = self.client.get(route, secure=True)
                self.assertContains(response, f'<p lang="{language}" dir="{direction}">{wording}</p>', html=True)
                for other_wording in set(self.activity.instructions.values()) - {wording}:
                    self.assertNotContains(response, other_wording)
                if language == 'ar':
                    self.assertContains(response, 'Instructions unavailable')
                    self.assertNotContains(response, 'Fictional legacy instructions')

    def test_only_the_visible_page_gets_media_checks_and_counts_keep_their_explicit_scope(self):
        fillers = [self.legacy_publication(f'A legacy entry {index:02d}') for index in range(24)]
        checked = []
        def prepare_visible(rows):
            rows = list(rows)
            checked.extend(activity.pk for activity in rows)
            return prepare_activities(rows)
        with patch('catalog.presentation_availability.prepare_activities', side_effect=prepare_visible):
            response = self.library()
        self.assertEqual(response.context['result_count'], 25)
        self.assertEqual(len(checked), 12)
        self.assertNotIn(self.activity.pk, checked)
        self.assertEqual(response.context['available_on_page'], 0)
        self.assertEqual(response.context['unavailable_on_page'], 12)
        self.assertContains(response, 'catalogue entries found')
        self.assertEqual({row['code']:row['count'] for row in response.context['arabic_collections']},
            {'ar-msa-pilot':25, 'ar-dz-pilot':0})
        last = self.library(page=3)
        self.assertEqual(last.context['available_on_page'], 1)
        self.assertEqual(last.context['unavailable_on_page'], 0)

    def test_filters_current_versions_and_legacy_order_inputs_are_preserved(self):
        other = self.legacy_publication('Other fictional variety', variety=self.other_variety)
        original = self.activity
        program = self.program()
        newer = self.legacy_publication('Newer unavailable publication', series=original.series, version=2)
        page = self.library(variety=self.variety.code, content_language='ar', kind='word_pair', q='newer')
        self.assertEqual([activity.pk for activity in page.context['page']], [newer.pk])
        self.assert_unavailable_card(page, newer)
        self.assertFalse(ProgramForm(child=self.child).fields['activities'].queryset.filter(pk=original.pk).exists())
        self.assertFalse(ProgramForm(self.values([original]), child=self.child).is_valid())
        self.assertEqual(program.items.get().activity_id, original.pk)
        # A qualified older assigned version remains inspectable under the existing contract.
        self.assertEqual(self.client.get(reverse('activity_detail', args=[original.pk])).status_code, 200)
        self.assertEqual(self.library(content_language='en').context['result_count'], 0)
        self.assertEqual(self.library(variety=self.other_variety.code).context['result_count'], 1)

    def test_legacy_valid_form_without_explicit_order_still_accepts_available_content(self):
        form = ProgramForm(self.values(), child=self.child)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual([activity.pk for activity in form.cleaned_data['activities']], [self.activity.pk])
        ordered = ProgramForm({**self.values(), 'activity_order':str(self.activity.pk)}, child=self.child)
        self.assertTrue(ordered.is_valid(), ordered.errors)

    def test_selected_post_checks_do_not_scan_other_catalogue_entries(self):
        ignored = self.legacy_publication('Unselected legacy input')
        checked = []
        def selected(rows):
            rows = list(rows)
            checked.extend(activity.pk for activity in rows)
            return prepare_activities(rows)
        with patch('catalog.presentation_availability.prepare_activities', side_effect=selected):
            form = ProgramForm(self.values(), child=self.child)
            self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(checked, [self.activity.pk])
        self.assertNotIn(ignored.pk, checked)

    def test_presentation_cache_is_request_local_and_invalidated_with_the_authoritative_scope(self):
        getter = Activity.usable.fget
        calls = []
        def usable(activity):
            calls.append(activity.pk)
            return getter(activity)
        with patch.object(Activity, 'usable', property(usable)):
            with integrity_scope():
                self.assertTrue(prepare_availability([self.activity])[0].presentation_available)
                self.assertTrue(prepare_availability([self.activity])[0].presentation_available)
                self.assertEqual(calls, [self.activity.pk])
                invalidate_integrity()
                prepare_availability([self.activity])
                self.assertEqual(calls, [self.activity.pk] * 2)
            with integrity_scope():
                prepare_availability([self.activity])
                self.assertEqual(calls, [self.activity.pk] * 3)

    def test_no_demo_publication_is_discovered_in_real_mode(self):
        example = Activity.objects.create(variety=self.variety, series=uuid.uuid4(),
            title='Fictional demo', word_a='demo-a', word_b='demo-b', contrast='demo',
            instructions={'en':'Fictional'}, is_demo=True,
            image_a='editorial/cat.svg', image_b='editorial/dog.svg')
        # Existing demo publication retained from an earlier demonstration environment.
        Activity.objects.filter(pk=example.pk).update(state='published')
        self.assertNotIn(example.pk, [activity.pk for activity in self.library().context['page']])
        self.assertFalse(ProgramForm(child=self.child).fields['activities'].queryset.filter(pk=example.pk).exists())
        self.assertEqual(self.client.get(reverse('activity_detail', args=[example.pk])).status_code, 404)
