import copy
import uuid
import json
import io
import tempfile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.core.files.base import ContentFile
from care.models import FamilyLink
from catalog.models import EditorialGrant, Variety, MediaAsset
from core.models import User, Membership, Organization
from .models import ClinicalGoal, ProbeDefinition, ProbeAdministration, ProbeRating, ProbeRatingRevision, ProbeExposure, HomePracticeFeedback
from .tests import install_fixture, definition, goal, start, rating as rating_data
from .services import save_rating, finalize_administration, share_summary, create_coaching, transition_definition, create_definition


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class FollowupViewTests(TestCase):
    def setUp(self):
        install_fixture(self)
        foreign_org = Organization.objects.create(name='Other fixture')
        Membership.objects.create(user=self.foreign, organization=foreign_org, role='clinician')
        self.probe = definition(self, 2)
        self.objective = goal(self, self.probe)
        self.administration = start(self, self.probe, self.objective)
        self.coaching = create_coaching(self.pro, self.child, {'variety': self.variety, 'instruction_language': 'fr', 'instructions': 'Shared instructions only', 'example': 'Shown example', 'accompanied_trial': 'Accompanied trial', 'understanding_checked': False, 'clinician_note': 'PRIVATE-CLINICIAN-SENTINEL', 'next_review': None})
        self.client.force_login(self.pro)

    def url(self, name, *args):
        return reverse('followup:' + name, args=args)

    def finish(self):
        for item in self.probe.items:
            save_rating(self.pro, self.administration, item['id'], rating_data())
        return finalize_administration(self.pro, self.administration)

    def design_payload(self, probe=None):
        from .forms import DefinitionForm, ItemForm
        item = {**self.probe.items[0], 'meaning': 'Synthetic word meaning', 'segments': ['p'], 'target_occurrences': [{'index': 0, 'phoneme': 'p', 'position': 'initial'}], 'familiarity_note': 'Synthetic documentation', 'review_note': 'Synthetic review only'}
        data = {'title': 'Designed synthetic draft', 'variety': str(self.variety.pk), 'protocol': 'Original fictional protocol', 'task': 'naming', 'target_phoneme': 'p', 'target_position': 'initial', 'context_key': 'isolated_word', 'rights': 'Synthetic provenance, not a release', 'rights_status': 'unknown', 'evidence': json.dumps({'source_context': 'Synthetic design evidence'}), 'is_demo': 'on', 'items-TOTAL_FORMS': '3', 'items-INITIAL_FORMS': '1' if probe else '0', 'items-MIN_NUM_FORMS': '0', 'items-MAX_NUM_FORMS': '60'}
        if probe:
            for key in DefinitionForm.base_fields:
                value = probe.target_scope.get('context', '') if key == 'context_key' else getattr(probe, key)
                data[key] = str(value.pk) if key == 'variety' else json.dumps(value) if key == 'evidence' else 'on' if value is True else '' if value is False else value
            item = {**item, **probe.items[0]}
        for key in ItemForm.base_fields:
            value = item.get(key, '')
            if key == 'segments':
                value = '\n'.join(value or [])
            elif key == 'accepted_variants':
                value = '\n'.join(f"{v['id']} | {v['label']} | {v.get('ipa', '')}" for v in value)
            elif key == 'target_occurrences':
                value = json.dumps(value or [])
            elif isinstance(value, bool):
                value = 'on' if value else ''
            data['items-0-' + key] = value if value is not None else ''
        for number in [1, 2]:
            data[f'items-{number}-target_occurrence_index'] = '0'
            data[f'items-{number}-selected_attempt'] = '1'
            data[f'items-{number}-exposure_plan'] = 'trained'
        return data

    def test_external_exposure_is_professional_only_and_does_not_rewrite_snapshot(self):
        original = copy.deepcopy(self.administration.snapshot)
        word = self.probe.items[1]['word']
        payload = {'variety': str(self.variety.pk), 'word': word, 'status': 'trained', 'note': 'Synthetic external practice declared by clinician', 'occurred_at': ''}
        url = self.url('exposure_create', self.child.pk)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(ProbeExposure.objects.filter(child=self.child, word=word, status='trained').count(), 1)
        self.administration.refresh_from_db()
        self.assertEqual(self.administration.snapshot, original)
        response = self.client.get(self.url('report', self.administration.pk))
        self.assertEqual(response.context['contamination'][0]['word'], word)
        for user in [self.family, self.editor, self.foreign]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, payload).status_code, 404)

    def test_all_professional_pages_render_three_languages_with_ipa_direction(self):
        self.finish()
        pages = [('index', []), ('definition_list', []), ('definition_detail', [self.probe.pk]), ('goal_detail', [self.objective.pk]), ('goal_create', [self.child.pk]), ('administration_start', [self.objective.pk]), ('administration_detail', [self.administration.pk]), ('rating', [self.administration.pk, self.probe.items[0]['id']]), ('report', [self.administration.pk]), ('report_print', [self.administration.pk]), ('share', [self.administration.pk]), ('coaching_create', [self.child.pk]), ('coaching_detail', [self.coaching.pk]), ('coaching_print', [self.coaching.pk]), ('home_feedback', [self.coaching.pk])]
        for language in ['fr', 'en', 'ar']:
            with translation.override(language):
                for name, args in pages:
                    response = self.client.get(self.url(name, *args))
                    self.assertEqual(response.status_code, 200, (language, name))
                    self.assertContains(response, f'lang="{language}"')
                self.assertContains(self.client.get(self.url('report_print', self.administration.pk)), 'dir="ltr"')

    def test_private_endpoints_and_exports_denied_to_family_editor_and_foreign_clinician(self):
        self.finish()
        private = [('goal_detail', [self.objective.pk]), ('goal_create', [self.child.pk]), ('goal_close', [self.objective.pk]), ('administration_start', [self.objective.pk]), ('administration_detail', [self.administration.pk]), ('administration_media', [self.administration.pk, self.probe.items[0]['id'], 'image']), ('rating', [self.administration.pk, self.probe.items[0]['id']]), ('administration_finalize', [self.administration.pk]), ('report', [self.administration.pk]), ('report_csv', [self.administration.pk]), ('report_print', [self.administration.pk]), ('share', [self.administration.pk]), ('share_revoke', [self.administration.pk]), ('coaching_create', [self.child.pk])]
        for user in [self.family, self.editor, self.foreign]:
            self.client.force_login(user)
            for name, args in private:
                self.assertEqual(self.client.post(self.url(name, *args), {}).status_code, 404, (user.username, name))
                if name not in ['share_revoke', 'goal_close']:
                    self.assertEqual(self.client.get(self.url(name, *args)).status_code, 404, (user.username, name))

    def test_cabinet_manager_does_not_inherit_clinical_scope(self):
        manager = User.objects.create_user(username='same-cabinet-owner', email='owner@example.test')
        Membership.objects.create(user=manager, organization=self.organization, role='owner')
        self.client.force_login(manager)
        self.assertEqual(self.client.get(self.url('report', self.administration.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('rating', self.administration.pk, self.probe.items[0]['id']), rating_data()).status_code, 404)

    def test_share_family_receives_only_chosen_text_and_revocation_is_effective(self):
        self.finish()
        shared = 'Text selected expressly by the responsible clinician.'
        response = self.client.post(self.url('share', self.administration.pk), {'text': shared, 'scope_confirmed': 'on'})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.family)
        response = self.client.get(self.url('family_summary', self.administration.pk))
        self.assertContains(response, shared)
        self.assertNotContains(response, self.probe.items[1]['word'])
        self.assertNotContains(response, 'TARGET_ACCEPTABLE')
        self.assertNotContains(response, 'PRIVATE-CLINICIAN-SENTINEL')
        self.client.force_login(self.pro)
        self.assertEqual(self.client.post(self.url('share_revoke', self.administration.pk)).status_code, 302)
        self.client.force_login(self.family)
        self.assertEqual(self.client.get(self.url('family_summary', self.administration.pk)).status_code, 404)

    def test_coaching_parent_is_read_only_understanding_is_not_self_approved(self):
        self.client.force_login(self.family)
        for name in ['coaching_detail', 'coaching_print']:
            response = self.client.get(self.url(name, self.coaching.pk))
            self.assertContains(response, 'Shared instructions only')
            self.assertNotContains(response, 'PRIVATE-CLINICIAN-SENTINEL')
            self.assertNotContains(response, 'name="understanding_checked"')
        self.client.post(self.url('coaching_detail', self.coaching.pk), {'understanding_checked': 'on'})
        self.coaching.refresh_from_db()
        self.assertFalse(self.coaching.understanding_checked)

    def test_family_link_revocation_removes_guidance_and_feedback_access(self):
        self.finish()
        share_summary(self.pro, self.administration, 'Shared summary')
        FamilyLink.objects.filter(user=self.family, child=self.child).update(active=False)
        self.client.force_login(self.family)
        for name, pk in [('family_summary', self.administration.pk), ('coaching_detail', self.coaching.pk), ('coaching_print', self.coaching.pk), ('home_feedback', self.coaching.pk)]:
            self.assertEqual(self.client.get(self.url(name, pk)).status_code, 404)
            self.assertEqual(self.client.post(self.url(name, pk), {}).status_code, 404)

    def test_home_declaration_is_idempotent_and_never_creates_a_rating(self):
        self.client.force_login(self.family)
        key = uuid.uuid4()
        data = {'participation': 'stopped', 'support_used': 'Support shown by clinician', 'difficulty': 'help', 'stop_reason': 'Tired', 'comment': 'Fictional parent declaration', 'key': key, 'code': 'TARGET_ACCEPTABLE', 'correct': 'true', 'understanding_checked': 'on'}
        for _ in range(2):
            self.assertEqual(self.client.post(self.url('home_feedback', self.coaching.pk), data).status_code, 302)
        self.assertEqual(HomePracticeFeedback.objects.filter(author=self.family).count(), 1)
        self.assertFalse(ProbeRating.objects.exists())
        self.coaching.refresh_from_db()
        self.assertFalse(self.coaching.understanding_checked)
        data.pop('stop_reason')
        data['key'] = uuid.uuid4()
        self.assertEqual(self.client.post(self.url('home_feedback', self.coaching.pk), data).status_code, 200)
        self.assertEqual(HomePracticeFeedback.objects.count(), 1)

    def test_finalization_double_click_and_reasoned_correction_preserve_original_summary(self):
        for item in self.probe.items:
            save_rating(self.pro, self.administration, item['id'], rating_data())
        for _ in range(2):
            self.assertEqual(self.client.post(self.url('administration_finalize', self.administration.pk), {'reviewed': 'on'}).status_code, 302)
        self.administration.refresh_from_db()
        original = copy.deepcopy(self.administration.summary_snapshot)
        correction = rating_data('TARGET_INCORRECT', attempt_index=99)
        correction['reason'] = 'Fictional correction after review.'
        response = self.client.post(self.url('rating', self.administration.pk, self.probe.items[0]['id']), correction)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProbeRatingRevision.objects.count(), 1)
        self.assertEqual(ProbeRatingRevision.objects.get().data['attempt_index'], 1)
        self.administration.refresh_from_db()
        self.assertEqual(self.administration.summary_snapshot, original)

    def test_csv_is_utf8_private_and_formula_safe(self):
        for item in self.probe.items:
            save_rating(self.pro, self.administration, item['id'], rating_data(assistance='=synthetic_formula'))
        response = self.client.get(self.url('report_csv', self.administration.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        self.assertIn('private, no-store', response.headers['Cache-Control'])
        self.assertIn("'=synthetic_formula", response.content.decode('utf-8-sig'))

    def test_reviewer_disciplines_and_editor_controls_are_scoped(self):
        reviewer = User.objects.create_user(username='clinical-review-fixture', email='review@example.test')
        EditorialGrant.objects.create(user=reviewer, variety=self.variety, clinical_review=True)
        transition_definition(self.pro, self.probe, 'review')
        self.client.force_login(reviewer)
        response = self.client.get(self.url('definition_detail', self.probe.pk))
        self.assertContains(response, 'value="clinical"')
        self.assertNotContains(response, 'value="linguistic"')
        self.assertNotContains(response, self.url('definition_clone', self.probe.pk))
        self.assertEqual(self.client.post(self.url('definition_detail', self.probe.pk), {'kind': 'linguistic', 'approved': 'on', 'note': 'Forbidden', 'competence': 'No actual competence claim'}).status_code, 403)
        self.assertEqual(self.client.post(self.url('definition_clone', self.probe.pk)).status_code, 403)
        self.assertEqual(self.client.post(self.url('definition_transition', self.probe.pk), {'state': 'approved'}).status_code, 403)

    def test_real_draft_start_remains_blocked_via_direct_post(self):
        real = definition(self, 1)
        # A new unpublished definition is not a clinical release.
        from .services import create_definition
        real = create_definition(self.pro, {'variety': self.variety, 'title': 'Unreleased original draft', 'protocol': 'Draft only', 'task': 'naming', 'target_phoneme': 'p', 'target_position': 'initial', 'target_scope': {'position': 'initial', 'context': 'isolated_word'}, 'items': real.items, 'is_demo': False})
        count = ProbeAdministration.objects.count()
        data = {'observation_scope': 'goal', 'place': 'Fixture', 'task': 'naming', 'instructions': 'Observe only', 'attempt_rule': 'First attempt', 'key': uuid.uuid4(), 'familiarity-known_0': 'familiar', 'familiarity-note_0': ''}
        response = self.client.post(self.url('administration_start', self.objective.pk) + '?definition=' + str(real.pk), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProbeAdministration.objects.count(), count)
        self.assertTrue(response.context['form'].non_field_errors())

    def test_editor_can_design_clone_and_edit_preserving_imported_metadata(self):
        self.client.force_login(self.editor)
        response = self.client.post(self.url('definition_create'), self.design_payload())
        self.assertEqual(response.status_code, 302, response.context and (response.context['form'].errors, response.context['item_forms'].errors, response.context['item_forms'].non_form_errors()))
        designed = ProbeDefinition.objects.get(title='Designed synthetic draft')
        self.assertEqual(designed.items[0]['segments'], ['p'])
        self.assertEqual(designed.items[0]['target_occurrences'][0]['index'], 0)
        self.assertIsNone(designed.organization_id)
        original = copy.deepcopy(designed.items)
        original[0]['import_provenance'] = {'source': 'fixture original', 'occurrences_count': 1}
        designed.items = original
        designed.save()
        self.assertEqual(self.client.post(self.url('definition_clone', designed.pk)).status_code, 302)
        cloned = ProbeDefinition.objects.get(series=designed.series, version=2)
        data = self.design_payload(cloned)
        data['title'] = 'Edited cloned draft'
        data['items-0-id'] = 'renamed-explicitly'
        response = self.client.post(self.url('definition_edit', cloned.pk), data)
        self.assertEqual(response.status_code, 302, response.context and response.context['item_forms'].errors)
        cloned.refresh_from_db()
        self.assertEqual(cloned.items[0]['import_provenance'], original[0]['import_provenance'])
        self.assertEqual(cloned.items[0]['target_occurrences'], original[0]['target_occurrences'])
        self.assertEqual(cloned.evidence, designed.evidence)
        self.assertEqual(cloned.state, 'draft')
        designed.refresh_from_db()
        self.assertEqual(designed.items, original)
        self.assertEqual(designed.title, 'Designed synthetic draft')

    def test_clinician_can_clone_shared_design_into_own_cabinet_without_editing_original(self):
        shared = create_definition(self.editor, {'variety': self.variety, 'title': 'Shared original design fixture', 'protocol': 'Unreleased fictional design', 'task': 'naming', 'target_phoneme': 'p', 'target_position': 'initial', 'target_scope': {'position': 'initial', 'context': 'isolated_word'}, 'items': self.probe.items, 'is_demo': True})
        response = self.client.get(self.url('definition_detail', shared.pk))
        self.assertContains(response, self.url('definition_clone', shared.pk))
        self.assertNotContains(response, self.url('definition_edit', shared.pk))
        self.assertEqual(self.client.post(self.url('definition_clone', shared.pk)).status_code, 302)
        cloned = ProbeDefinition.objects.get(series=shared.series, version=2)
        self.assertEqual(cloned.organization_id, self.organization.pk)
        self.assertEqual(cloned.authored_by_id, self.pro.pk)
        self.assertEqual(cloned.state, 'draft')
        self.assertEqual(self.client.get(self.url('definition_edit', shared.pk)).status_code, 403)

    def test_start_form_binds_exact_version_conditions_and_familiarity_idempotently(self):
        key = uuid.uuid4()
        data = {'observation_scope': 'goal', 'definition': uuid.uuid4(), 'place': 'Synthetic room', 'task': 'naming', 'fatigue': 'Comfortable fixture', 'noise': 'Quiet fixture', 'instructions': 'Predetermined instructions', 'attempt_rule': 'First attempt', 'key': key}
        for number in range(len(self.probe.items)):
            data[f'familiarity-known_{number}'] = 'familiar'
            data[f'familiarity-note_{number}'] = 'Synthetic familiarity note'
        url = self.url('administration_start', self.objective.pk) + '?definition=' + str(self.probe.pk)
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        created = ProbeAdministration.objects.get(idempotency_key=key)
        self.assertEqual(created.definition_id, self.probe.pk)
        self.assertEqual(created.conditions['place'], 'Synthetic room')
        self.assertTrue(all(entry['familiar'] for entry in created.familiarity.values()))
        first = self.probe.items[0]['id']
        self.assertEqual(self.client.post(self.url('rating', created.pk, first), rating_data()).status_code, 302)
        self.assertContains(self.client.get(self.url('administration_detail', created.pk)), '1 / 2')
        wrong = create_definition(self.pro, {'variety': self.variety, 'title': 'Wrong target draft', 'protocol': 'Fictional only', 'task': 'naming', 'target_phoneme': 'k', 'target_position': 'initial', 'target_scope': {'position': 'initial', 'context': 'isolated_word'}, 'items': self.probe.items, 'is_demo': True})
        data['key'] = uuid.uuid4()
        response = self.client.post(self.url('administration_start', self.objective.pk) + '?definition=' + str(wrong.pk), data)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ProbeAdministration.objects.filter(idempotency_key=data['key']).exists())

    def test_goal_close_is_post_only_scoped_and_preserves_history(self):
        self.assertEqual(self.client.get(self.url('goal_close', self.objective.pk)).status_code, 405)
        for _ in range(2):
            self.assertEqual(self.client.post(self.url('goal_close', self.objective.pk)).status_code, 302)
        self.objective.refresh_from_db()
        self.assertFalse(self.objective.active)
        self.assertEqual(self.client.get(self.url('administration_detail', self.administration.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.url('administration_start', self.objective.pk)).status_code, 403)
        response = self.client.get(self.url('goal_detail', self.objective.pk))
        self.assertNotContains(response, self.url('administration_start', self.objective.pk))
        self.assertTrue(ProbeAdministration.objects.filter(pk=self.administration.pk).exists())

    def test_report_uses_original_goal_snapshot_after_live_goal_changes(self):
        before = self.objective.functional_goal
        ClinicalGoal.objects.filter(pk=self.objective.pk).update(functional_goal='Changed current goal sentinel')
        response = self.client.get(self.url('report', self.administration.pk))
        self.assertContains(response, before)
        self.assertNotContains(response, 'Changed current goal sentinel')

    def test_adult_instruction_language_is_explicit_and_not_automatically_translated(self):
        with translation.override('ar'):
            response = self.client.get(self.url('coaching_create', self.child.pk))
            self.assertEqual(response.context['form'].initial['instruction_language'], 'ar')
        self.client.force_login(self.family)
        with translation.override('ar'):
            response = self.client.get(self.url('coaching_detail', self.coaching.pk))
            self.assertTrue(response.context['instruction_language_mismatch'])
            self.assertContains(response, 'Shared instructions only')
            self.assertEqual(response.context['instruction_language_label'], 'Français')

    def test_probe_media_is_private_and_snapshot_bound(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(buffer, format='PNG')
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            asset = MediaAsset.objects.create(file=ContentFile(buffer.getvalue(), name='synthetic-word.png'), kind='image', rights='Synthetic fixture only', uploaded_by=self.pro)
            items = copy.deepcopy(self.probe.items)
            items[0]['image_asset'] = str(asset.pk)
            probe = create_definition(self.pro, {'variety': self.variety, 'title': 'Media fixture', 'protocol': 'Fictional only', 'task': 'naming', 'target_phoneme': 'p', 'target_position': 'initial', 'target_scope': {'position': 'initial', 'context': 'isolated_word'}, 'items': items, 'is_demo': True})
            objective = goal(self, probe)
            admin = start(self, probe, objective)
            url = self.url('administration_media', admin.pk, items[0]['id'], 'image')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertEqual(response.content, buffer.getvalue())
            self.client.force_login(self.family)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.get(self.url('definition_media', probe.pk, items[0]['id'], 'image')).status_code, 404)
            self.client.force_login(self.pro)
            MediaAsset.objects.filter(pk=asset.pk).update(technical_metadata={**asset.technical_metadata, 'sha256': '0' * 64})
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_linked_protocol_is_frozen_before_any_administration(self):
        probe = definition(self, 1)
        goal(self, probe)
        self.assertFalse(probe.administrations.exists())
        url = self.url('definition_edit', probe.pk)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        response = self.client.get(self.url('definition_detail', probe.pk))
        self.assertNotContains(response, url)
        self.assertContains(response, self.url('definition_clone', probe.pk))


    def test_audio_models_support_ranges_without_family_access(self):
        from core.testing import pcm_fixture
        data=pcm_fixture()
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            asset=MediaAsset.objects.create(file=ContentFile(data,name='technical-tone.wav'),kind='audio',rights='Software fixture only',uploaded_by=self.pro)
            items=copy.deepcopy(self.probe.items);items[0]['audio_asset']=str(asset.pk)
            probe=create_definition(self.pro, {'variety':self.variety,'title':'Audio range fixture','protocol':'Fictional only','task':'naming','target_phoneme':'p','target_position':'initial','target_scope':{'position':'initial','context':'isolated_word'},'items':items,'is_demo':True})
            objective=goal(self,probe);admin=start(self,probe,objective)
            for url in [self.url('administration_media',admin.pk,items[0]['id'],'audio'),self.url('definition_media',probe.pk,items[0]['id'],'audio')]:
                self.client.force_login(self.pro)
                response=self.client.get(url,HTTP_RANGE='bytes=0-43')
                self.assertEqual(response.status_code,206);self.assertEqual(response.content,data[:44])
                self.client.force_login(self.family)
                self.assertEqual(self.client.get(url,HTTP_RANGE='bytes=0-43').status_code,404)
