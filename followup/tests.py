"""Meaningful isolated follow-up safeguards; fixtures are not clinical approvals."""
import copy
import json
import io
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.utils.translation import gettext as _
from care.models import Child, FamilyLink
from catalog.models import Variety, EditorialGrant, MediaAsset
from core.models import User, Organization, Membership, Entitlement
from core.testing import pcm_fixture
from .models import ClinicalGoal, ProbeDefinition, ProbeAdministration, ProbeRatingRevision, ProbeExposure, ParentCoaching, HomePracticeFeedback
from .imports import import_definitions
from .services import (create_goal, create_definition, update_definition, clone_definition, start_administration, save_rating,
    finalize_administration, professional_report, family_summary, share_summary, record_exposure, reserved_words_for,
    create_coaching, coaching_family_data, record_home_practice, erase_child_followup, retention_date, transition_definition,
    close_goal, content_reasons, review_definition)
from .validation import validate_items

HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


def install_fixture(case):
    case.pro = User.objects.create_user(username='followup-clinician', email='followup-clinician@example.test')
    case.family = User.objects.create_user(username='followup-family', email='followup-family@example.test')
    case.editor = User.objects.create_user(username='followup-editor', email='followup-editor@example.test')
    case.foreign = User.objects.create_user(username='followup-foreign', email='followup-foreign@example.test')
    case.organization = Organization.objects.create(name='Follow-up fixture · fictif')
    Membership.objects.create(user=case.pro, organization=case.organization, role='clinician')
    Entitlement.objects.create(organization=case.organization, expires_at=timezone.now() + timezone.timedelta(days=20), child_quota=5, practitioner_quota=5)
    case.variety = Variety.objects.create(code='fr-fr-pilot', language='fr', label='Synthetic French fixture')
    case.child = Child.objects.create(code='Observation · fictif', age_years=5, responsible=case.pro, organization=case.organization)
    case.child.varieties.add(case.variety)
    FamilyLink.objects.create(child=case.child, user=case.family)
    EditorialGrant.objects.create(user=case.editor, variety=case.variety, edit=True, publish=True)


def item(index, reserved=False):
    return {'id': 'fixture-' + str(index), 'word': 'mot-' + str(index), 'ipa': '/p/', 'target_definition': 'Synthetic first occurrence',
        'target_occurrence_index': 0, 'selected_attempt': 1, 'exposure_plan': 'reserved' if reserved else 'trained',
        'accepted_variants': [{'id': 'regional', 'label': 'Predeclared synthetic variant'}], 'image_asset': None, 'audio_asset': None,
        'familiarity_verified': False, 'reviewed': False}


def definition(case, count=2):
    return create_definition(case.pro, {'variety': case.variety, 'title': 'Synthetic unapproved protocol', 'protocol': 'Original synthetic protocol, never clinically approved.',
        'task': 'picture_naming', 'target_phoneme': 'p', 'target_position': 'initial', 'items': [item(i, i % 2 == 1) for i in range(count)], 'is_demo': True})


def goal(case, probe):
    return create_goal(case.pro, case.child, {'variety': case.variety, 'target_phoneme': 'p', 'target_position': 'initial',
        'rationale': 'Synthetic observation only', 'expected_realization': '/p/', 'functional_goal': 'Observe synthetic responses.',
        'probe_definition': probe})


def start(case, probe, objective, key=None):
    return start_administration(case.pro, objective, probe, {'attempt_rule': 'First predetermined attempt', 'task': 'naming'},
        {i['id']: {'familiar': False, 'note': 'Synthetic familiarity only'} for i in probe.items}, key)


def rating(code='TARGET_ACCEPTABLE', **changes):
    data = {'attempt_index': 1, 'elicitation': 'naming', 'assistance': '', 'transcription': '', 'code': code,
        'variant_id': 'regional' if code == 'VARIANT_ACCEPTABLE' else '', 'exclusion_reason': 'refusal' if code == 'NOT_SCORABLE' else '',
        'error_type': 'omission' if code == 'TARGET_INCORRECT' else '',
        'attempted_expected_word': code not in ['NOT_SCORABLE', 'NOT_PRESENTED'],
        'target_identifiable': code not in ['NOT_SCORABLE', 'NOT_PRESENTED']}
    data.update(changes)
    return data


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class FollowupTests(TestCase):
    def setUp(self):
        install_fixture(self)

    def prepare(self, count=2):
        self.probe = definition(self, count)
        self.goal = goal(self, self.probe)
        self.admin = start(self, self.probe, self.goal)
        return self.admin

    def test_descriptive_ratio_six_over_nine_and_exclusions(self):
        self.prepare(11)
        codes = ['TARGET_ACCEPTABLE'] * 5 + ['VARIANT_ACCEPTABLE'] + ['TARGET_INCORRECT'] * 3 + ['NOT_SCORABLE'] * 2
        for i, code in zip(self.probe.items, codes):
            save_rating(self.pro, self.admin, i['id'], rating(code))
        finished = finalize_administration(self.pro, self.admin)
        groups = professional_report(self.pro, finished)['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]['numerator'], groups[0]['denominator'], groups[0]['excluded']), (6, 9, 2))
        self.assertAlmostEqual(groups[0]['ratio'], 6/9)
        self.assertEqual(finalize_administration(self.pro, finished).finalized_at, finished.finalized_at)

    def test_zero_denominator_and_not_presented_are_not_errors(self):
        self.prepare()
        save_rating(self.pro, self.admin, 'fixture-0', rating('NOT_SCORABLE'))
        save_rating(self.pro, self.admin, 'fixture-1', rating('NOT_PRESENTED'))
        group = professional_report(self.pro, finalize_administration(self.pro, self.admin))['groups'][0]
        self.assertIsNone(group['ratio'])
        self.assertEqual((group['denominator'], group['excluded'], group['not_presented']), (0, 1, 1))

    def test_audible_omission_is_error_refusal_requires_exclusion(self):
        self.prepare()
        with self.assertRaises(ValidationError):
            save_rating(self.pro, self.admin, 'fixture-0', rating('TARGET_INCORRECT', attempted_expected_word=False))
        save_rating(self.pro, self.admin, 'fixture-0', rating('TARGET_INCORRECT'))
        with self.assertRaises(ValidationError):
            save_rating(self.pro, self.admin, 'fixture-1', rating('NOT_SCORABLE', exclusion_reason=''))
        save_rating(self.pro, self.admin, 'fixture-1', rating('NOT_SCORABLE'))

    def test_variant_and_predetermined_attempt_and_item_identity(self):
        self.prepare()
        for key, data in [('fixture-0', rating('VARIANT_ACCEPTABLE', variant_id='invented')),
                          ('fixture-0', rating(attempt_index=2)), ('not-an-item', rating())]:
            with self.assertRaises(ValidationError):
                save_rating(self.pro, self.admin, key, data)
        save_rating(self.pro, self.admin, 'fixture-0', rating('VARIANT_ACCEPTABLE'))

    def test_aid_imitation_and_exposure_are_separate_groups(self):
        probe = definition(self, 3)
        objective = goal(self, probe)
        record_exposure(self.pro, self.child, self.variety, probe.items[0]['word'], 'trained', 'Synthetic history')
        record_exposure(self.pro, self.child, self.variety, probe.items[1]['word'], 'untrained', 'Explicit professional declaration')
        admin = start(self, probe, objective)
        for i, changes in zip(probe.items, [{}, {'elicitation':'imitation','assistance':'adult model'}, {'elicitation':'semantic_cue','assistance':'meaning cue'}]):
            save_rating(self.pro, admin, i['id'], rating(**changes))
        groups = professional_report(self.pro, finalize_administration(self.pro, admin))['groups']
        self.assertEqual({g['exposure'] for g in groups}, {'trained', 'untrained', 'uncertain'})
        self.assertEqual({g['elicitation'] for g in groups}, {'naming', 'imitation', 'semantic_cue'})
        self.assertEqual({g['variety'] for g in groups}, {'fr-fr-pilot'})

    def test_family_editor_foreign_cannot_start_rate_read_private_report(self):
        self.prepare()
        for actor in [self.family, self.editor, self.foreign]:
            with self.assertRaises((PermissionDenied, ValidationError)):
                start_administration(actor, self.goal, self.probe, {'attempt_rule':'first'}, {i['id']:{'familiar':True} for i in self.probe.items})
            with self.assertRaises((PermissionDenied, ValidationError)):
                save_rating(actor, self.admin, 'fixture-0', rating())
            with self.assertRaises(Http404):
                professional_report(actor, self.admin)

    def test_revoked_membership_and_transferred_responsibility_rechecked(self):
        self.prepare()
        Membership.objects.filter(user=self.pro).update(active=False)
        with self.assertRaises(ValidationError):
            save_rating(self.pro, self.admin, 'fixture-0', rating())
        Membership.objects.filter(user=self.pro).update(active=True)
        Membership.objects.create(user=self.foreign, organization=self.organization, role='clinician')
        self.child.responsible = self.foreign
        self.child.save()
        with self.assertRaises(ValidationError):
            finalize_administration(self.pro, self.admin)
        with self.assertRaises(Http404):
            professional_report(self.pro, self.admin)

    def test_explicit_family_sharing_hides_every_item_score_and_private_note(self):
        self.prepare()
        for i in self.probe.items:
            save_rating(self.pro, self.admin, i['id'], rating())
        finished = finalize_administration(self.pro, self.admin)
        with self.assertRaises(Http404):
            family_summary(self.family, finished)
        share_summary(self.pro, finished, 'Only this explicitly shared summary.')
        shown = family_summary(self.family, finished)
        self.assertEqual(shown['shared_text'], 'Only this explicitly shared summary.')
        self.assertFalse({'snapshot', 'items', 'ratings', 'groups', 'goal', 'conditions'} & set(shown))
        FamilyLink.objects.filter(child=self.child, user=self.family).update(active=False)
        with self.assertRaises(Http404):
            family_summary(self.family, finished)
        FamilyLink.objects.filter(child=self.child, user=self.family).update(active=True)
        share_summary(self.pro, finished, '')
        with self.assertRaises(Http404):
            family_summary(self.family, finished)

    def test_reasoned_correction_retains_original_rating_and_final_groups(self):
        self.prepare()
        for i in self.probe.items:
            save_rating(self.pro, self.admin, i['id'], rating())
        finished = finalize_administration(self.pro, self.admin)
        original = copy.deepcopy(finished.summary_snapshot)
        with self.assertRaises(ValidationError):
            save_rating(self.pro, finished, 'fixture-0', rating('TARGET_INCORRECT'))
        row = save_rating(self.pro, finished, 'fixture-0', rating('TARGET_INCORRECT'), 'Audible omission reviewed.')
        self.assertEqual(row.code, 'TARGET_ACCEPTABLE')
        self.assertEqual(ProbeRatingRevision.objects.count(), 1)
        report = professional_report(self.pro, finished)
        self.assertEqual(report['groups'][0]['numerator'], 1)
        self.assertEqual(report['original_groups'], original)
        row.code = 'TARGET_INCORRECT'
        with self.assertRaises(ValidationError):
            row.save()

    def test_frozen_protocol_and_conditions_remain_after_clone(self):
        self.prepare()
        prior = copy.deepcopy(self.admin.snapshot)
        self.probe.items[0]['word'] = 'changed'
        with self.assertRaises(ValidationError):
            self.probe.save()
        self.probe.refresh_from_db()
        clone = clone_definition(self.pro, self.probe)
        clone.items[0]['word'] = 'new version word'
        update_definition(self.pro, clone, {'items':clone.items})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.snapshot, prior)
        self.admin.conditions['attempt_rule'] = 'Choose the best answer after listening'
        with self.assertRaises(ValidationError):
            self.admin.save()

    def test_start_idempotence_rejects_changed_body(self):
        probe = definition(self); objective = goal(self, probe); key = uuid.uuid4()
        first = start(self, probe, objective, key)
        self.assertEqual(start(self, probe, objective, key).pk, first.pk)
        with self.assertRaises(ValidationError):
            start_administration(self.pro, objective, probe, {'attempt_rule':'different'}, first.familiarity, key)
        self.assertEqual(ProbeAdministration.objects.count(), 1)

    def test_incomplete_finalization_and_withdrawn_start_fail(self):
        self.prepare()
        with self.assertRaises(ValidationError):
            finalize_administration(self.pro, self.admin)
        self.assertEqual(ProbeAdministration.objects.get(pk=self.admin.pk).status, 'draft')
        self.probe.state = 'withdrawn'; self.probe.save()
        with self.assertRaises(ValidationError):
            start(self, self.probe, self.goal)
        self.assertEqual(professional_report(self.pro, self.admin)['snapshot']['title'], self.probe.title)

    def test_demo_requires_demo_mode_fictitious_child_and_original_drafts_stay_blocked(self):
        probe = definition(self); objective = goal(self, probe)
        with override_settings(DEMO_MODE=False), self.assertRaises(ValidationError):
            start(self, probe, objective)
        self.child.code = 'Unmarked profile'; self.child.save()
        with self.assertRaises(ValidationError):
            start(self, probe, objective)
        self.child.code = 'Observation · fictif'; self.child.save()
        values = {k:getattr(probe,k) for k in ['variety','title','protocol','task','target_phoneme','target_position','items']}
        real = create_definition(self.pro, {**values,'is_demo':False})
        with self.assertRaises(ValidationError):
            start(self, real, objective)
        with self.assertRaises(ValidationError):
            transition_definition(self.editor, probe, 'published')

    def test_original_import_repeated_no_duplicates_or_overwrite(self):
        Variety.objects.create(code='en-us-general-pilot', language='en', label='Synthetic English fixture')
        data = json.loads((Path(__file__).parent/'data'/'probes_draft.json').read_text(encoding='utf-8'))
        rows = import_definitions(data)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(created and not row.is_demo and row.state == 'draft' and not row.ready for row,created in rows))
        again = import_definitions(data)
        self.assertTrue(all(not created for _,created in again))
        self.assertEqual(ProbeDefinition.objects.count(), 2)
        changed = copy.deepcopy(data); changed['examples'][0]['items'][0]['word'] = 'different'
        with self.assertRaises(ValidationError):
            import_definitions(changed)
        self.assertEqual(ProbeDefinition.objects.count(), 2)

    def test_reservation_is_child_scoped_and_contamination_never_rewrites_snapshot(self):
        self.prepare()
        self.assertEqual(reserved_words_for(self.child, self.variety), {'mot-1'})
        before = copy.deepcopy(self.admin.snapshot)
        record_exposure(self.pro, self.child, self.variety, 'mot-1', 'trained', 'External practice later reported.')
        report = professional_report(self.pro, self.admin)
        self.assertEqual(report['snapshot'], before)
        self.assertEqual(report['contamination'][0]['original_exposure'], 'uncertain')
        self.assertEqual(report['contamination'][0]['item_key'], 'fixture-1')

    def test_parent_coaching_and_home_return_are_declarations_without_scores(self):
        coaching = create_coaching(self.pro, self.child, {'variety':self.variety,'instruction_language':'fr','instructions':'Shared training instructions',
            'example':'Practice example','clinician_note':'Private clinical information','understanding_checked':False})
        shown = coaching_family_data(self.family, coaching)
        self.assertNotIn('clinician_note', shown)
        self.assertEqual(shown['instruction_language'],'fr')
        with self.assertRaises(ValidationError):
            create_coaching(self.pro,self.child,{'variety':self.variety,'instructions':'Language must be explicit'})
        key = uuid.uuid4()
        data = {'participation':'stopped','difficulty':'difficult','support_used':'Adult help','stop_reason':'Fatigue','comment':'Outside-screen declaration'}
        report = record_home_practice(self.family, coaching, data, key)
        self.assertEqual(record_home_practice(self.family, coaching, data, key).pk, report.pk)
        self.assertFalse({'answer', 'correct', 'transcription'} & {f.name for f in report._meta.fields})
        with self.assertRaises(PermissionDenied):
            record_home_practice(self.editor, coaching, data)
        with self.assertRaises(ValidationError):
            record_home_practice(self.family, coaching, {**data,'stop_reason':''})
        FamilyLink.objects.filter(child=self.child,user=self.family).update(active=False)
        with self.assertRaises(PermissionDenied):
            record_home_practice(self.family, coaching, data)
        self.assertEqual(HomePracticeFeedback.objects.count(), 1)

    def test_exposure_and_coaching_retention_and_erasure_integrate(self):
        self.prepare()
        record_exposure(self.pro,self.child,self.variety,'mot-0','trained','Synthetic history')
        coaching = create_coaching(self.pro,self.child,{'variety':self.variety,'instruction_language':'fr','instructions':'Synthetic instruction'})
        record_home_practice(self.family,coaching,{'participation':'partial','difficulty':'help'})
        self.assertIsNotNone(retention_date(self.child))
        with transaction.atomic():
            erase_child_followup(self.child)
            self.child.delete()
        self.assertEqual(ProbeAdministration.objects.count(), 0)
        self.assertEqual(ClinicalGoal.objects.count(), 0)
        self.assertEqual(ProbeExposure.objects.count(), 0)
        self.assertEqual(HomePracticeFeedback.objects.count(), 0)

    def test_new_share_and_revocation_extend_retention_and_block_erasure(self):
        from core.models import AuditEvent, PrivacyRequest
        from core.complete_views import retention_anchor
        from core.services import resolve_privacy
        self.prepare()
        for row in self.probe.items:
            save_rating(self.pro,self.admin,row['id'],rating())
        self.admin = finalize_administration(self.pro,self.admin)
        old = timezone.now() - timezone.timedelta(days=100)
        ClinicalGoal.objects.filter(pk=self.goal.pk).update(created_at=old)
        ProbeAdministration.objects.filter(pk=self.admin.pk).update(started_at=old,finalized_at=old)
        self.admin.ratings.update(created_at=old)
        Child.objects.filter(pk=self.child.pk).update(created_at=old)
        self.child.refresh_from_db();self.admin.refresh_from_db()
        self.organization.retention_days=30;self.organization.save()
        request = PrivacyRequest.objects.create(organization=self.organization,child=self.child,requester=self.family,kind='erasure')
        data = {'decision':'erase','confirmation':self.child.code,'reason':'Fictional authorised request'}
        self.admin=share_summary(self.pro,self.admin,'New explicitly shared summary')
        self.assertGreaterEqual(retention_anchor(self.child),self.admin.shared_at)
        with self.assertRaises(ValidationError): resolve_privacy(self.pro,request.pk,data)
        self.admin=share_summary(self.pro,self.admin,'')
        self.assertIsNone(self.admin.shared_at)
        revoked = AuditEvent.objects.get(action='followup.summary_revoked',object_id=str(self.admin.pk))
        self.assertEqual(retention_date(self.child),revoked.created_at)
        self.assertGreaterEqual(retention_anchor(self.child),revoked.created_at)
        with self.assertRaises(ValidationError): resolve_privacy(self.pro,request.pk,data)
        # A different administration identity must not change this child's anchor.
        unrelated = AuditEvent.objects.create(organization=self.organization,actor=self.pro,action='followup.summary_shared',object_id=str(uuid.uuid4()))
        AuditEvent.objects.filter(pk=unrelated.pk).update(created_at=timezone.now()+timezone.timedelta(days=1))
        self.assertEqual(retention_date(self.child),revoked.created_at)
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        request.refresh_from_db();self.assertEqual(request.status,'pending')

    def test_media_bytes_and_rights_are_in_exact_protocol_digest(self):
        from PIL import Image
        import io
        image = io.BytesIO(); Image.new('RGB',(3,3)).save(image,format='PNG')
        (Path.cwd()/'work').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'work') as directory, override_settings(MEDIA_ROOT=directory):
            audio = MediaAsset.objects.create(file=ContentFile(pcm_fixture(),name='synthetic.wav'),kind='audio',rights='Synthetic fixture rights',uploaded_by=self.pro)
            picture = MediaAsset.objects.create(file=ContentFile(image.getvalue(),name='synthetic.png'),kind='image',rights='Synthetic fixture rights',uploaded_by=self.pro)
            probe = definition(self)
            probe.items[0].update(audio_asset=str(audio.pk),image_asset=str(picture.pk))
            probe.save()
            first = probe.fingerprint()
            # Out-of-band storage corruption must invalidate the exact digest.
            Path(audio.file.path).write_bytes(b'changed technical fixture bytes')
            self.assertNotEqual(first,probe.fingerprint())
            Path(audio.file.path).write_bytes(pcm_fixture())
            self.assertEqual(first,probe.fingerprint())
            MediaAsset.objects.filter(pk=audio.pk).update(rights='Changed rights statement')
            self.assertNotEqual(first,probe.fingerprint())

    def test_close_goal_is_scoped_idempotent_and_retains_snapshot(self):
        self.prepare()
        snapshot = copy.deepcopy(self.admin.snapshot)
        with self.assertRaises(PermissionDenied):
            close_goal(self.family, self.goal)
        with self.assertRaises(PermissionDenied):
            close_goal(self.foreign, self.goal)
        closed = close_goal(self.pro, self.goal)
        self.assertFalse(closed.active)
        self.assertFalse(close_goal(self.pro, closed).active)
        self.assertEqual(professional_report(self.pro, self.admin)['snapshot'], snapshot)
        self.assertEqual(reserved_words_for(self.child, self.variety), {'mot-1'})
        with self.assertRaises(PermissionDenied):
            start(self, self.probe, closed)

    def test_phoneme_indices_are_not_ipa_character_offsets_and_drafts_stay_incomplete(self):
        probe = definition(self, 1)
        values = copy.deepcopy(probe.items)
        # Nasal vowel is one phonemic segment, although multiple Unicode codepoints.
        values[0].update(ipa='/pɛ̃/', meaning='Synthetic meaning', segments=['p', 'ɛ̃'],
            target_occurrences=[{'index':0,'phoneme':'p','position':'initial'}])
        validate_items(values)
        values[0]['target_occurrence_index'] = 2
        with self.assertRaises(ValidationError): validate_items(values)
        values[0]['target_occurrence_index'] = 0
        values[0]['target_occurrences'][0]['phoneme'] = 'b'
        with self.assertRaises(ValidationError): validate_items(values)
        values[0]['target_occurrences'][0]['phoneme'] = 'p'
        probe.items = values; probe.save()
        metadata_reason = _('Real use requires a documented meaning and phonemic segmentation with a target index matching the protocol phoneme.')
        self.assertNotIn(metadata_reason, content_reasons(probe))
        probe.target_phoneme = 'b'; probe.save()
        self.assertIn(metadata_reason, content_reasons(probe))
        objective = goal(self, probe)
        with self.assertRaises(ValidationError): start(self, probe, objective)

    def test_comparison_tracks_exposure_familiarity_and_frozen_goal(self):
        self.prepare()
        for row in self.probe.items: save_rating(self.pro,self.admin,row['id'],rating())
        finalize_administration(self.pro,self.admin)
        second = start(self,self.probe,self.goal)
        for row in self.probe.items: save_rating(self.pro,second,row['id'],rating())
        finalize_administration(self.pro,second)
        self.assertTrue(professional_report(self.pro,second)['comparable'])
        familiar = copy.deepcopy(second.familiarity); familiar['fixture-0']['familiar'] = True
        changed_familiarity = start_administration(self.pro,self.goal,self.probe,second.conditions,familiar)
        for row in self.probe.items: save_rating(self.pro,changed_familiarity,row['id'],rating())
        self.assertFalse(professional_report(self.pro,changed_familiarity)['comparable'])
        record_exposure(self.pro,self.child,self.variety,'mot-1','trained','Synthetic later exposure')
        third = start(self,self.probe,self.goal)
        for row in self.probe.items: save_rating(self.pro,third,row['id'],rating())
        self.assertFalse(professional_report(self.pro,third)['comparable'])
        self.goal.expected_realization='New later goal criterion'; self.goal.save()
        first_report = professional_report(self.pro,self.admin)
        self.assertEqual(first_report['clinical_goal_snapshot']['expected_realization'],'/p/')
        self.assertNotEqual(first_report['goal'].expected_realization,first_report['clinical_goal_snapshot']['expected_realization'])

    def test_two_distinct_reviewers_exact_proofs_and_real_release_are_required(self):
        from qualification.test_support import evidence_fixture, competence_fixture, media_fixture, availability_fixture
        from qualification.models import EvidenceDocument
        from .services import _current_reviews
        (Path.cwd()/'work').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'work') as directory, override_settings(MEDIA_ROOT=directory,DEMO_MODE=False):
            competence_fixture(self.pro,self.variety,'clinical')
            competence_fixture(self.pro,self.variety,'linguistic')
            competence_fixture(self.foreign,self.variety,'linguistic')
            proofs = {category:evidence_fixture(self.variety,self.pro,category) for category in ['rights','familiarity','linguistic']}
            image = media_fixture(self.variety,self.pro,'image',proofs['rights'])
            audio = media_fixture(self.variety,self.pro,'audio',proofs['rights'])
            items = [item(0)]
            items[0].update(meaning='Synthetic meaning',segments=['p'],target_occurrences=[{'index':0,'phoneme':'p','position':'initial'}],
                familiarity_verified=True,reviewed=True,image_asset=str(image.pk),audio_asset=str(audio.pk))
            probe = create_definition(self.editor, {'variety':self.variety,'title':'Synthetic complete fixture','protocol':'Fictional test only',
                'task':'naming','target_phoneme':'p','target_position':'initial','items':items,'is_demo':False,
                'rights':'Fictional test only','rights_status':'original_documented',
                'evidence':{category+'_evidence':{'id':str(doc.pk),'sha256':doc.sha256} for category,doc in proofs.items()}})
            probe = transition_definition(self.editor,probe,'review')
            review_definition(self.pro,probe,'clinical',True,'Fictional test review','Fictional clinical competence')
            review_definition(self.pro,probe,'linguistic',True,'Fictional same-person review','Fictional linguistic competence')
            self.assertEqual(_current_reviews(probe),[])
            with self.assertRaises(ValidationError): transition_definition(self.editor,probe,'approved')
            review_definition(self.foreign,probe,'linguistic',True,'Fictional independent review','Fictional linguistic competence')
            probe = transition_definition(self.editor,probe,'approved')
            probe = transition_definition(self.editor,probe,'published')
            objective = goal(self,probe)
            objective.external_assessment_status='confirmed';objective.save()
            conditions = {'attempt_rule':'Predetermined first attempt'}
            familiar = {'fixture-0':{'familiar':True,'note':'Synthetic verified fixture'}}
            with self.assertRaises(ValidationError): start_administration(self.pro,objective,probe,conditions,familiar)
            availability_fixture('production_followup',self.variety,probe.fingerprint(),self.pro)
            real_admin = start_administration(self.pro,objective,probe,conditions,familiar)
            self.assertFalse(real_admin.snapshot['is_demo'])
            proof = proofs['familiarity']; proof.revoked=True;proof.revocation_reason='Fictional revocation';proof.save()
            self.assertFalse(probe.ready)
            with self.assertRaises(ValidationError): start_administration(self.pro,objective,probe,conditions,familiar)
            before = probe.fingerprint()
            rights = EvidenceDocument.objects.get(pk=proofs['rights'].pk)
            rights.revoked=True;rights.revocation_reason='Fictional media rights revocation';rights.save()
            self.assertNotEqual(before,probe.fingerprint())
            self.assertEqual(ProbeAdministration.objects.count(),1)

    def test_optional_demo_seed_is_idempotent_without_approvals_or_real_targets(self):
        from .models import ProbeReview
        self.pro.username='orthophoniste';self.pro.email='orthophoniste@demo.example';self.pro.save()
        self.child.code='Sami · fictif';self.child.save()
        english = Variety.objects.create(code='en-us-general-pilot',language='en',label='Synthetic English fixture')
        self.child.varieties.add(english)
        output = io.StringIO()
        call_command('seed_followup_demo',stdout=output)
        self.assertEqual((ProbeDefinition.objects.count(),ClinicalGoal.objects.count(),ParentCoaching.objects.count()),(4,2,6))
        first_goal = ClinicalGoal.objects.first(); close_goal(self.pro,first_goal)
        call_command('seed_followup_demo',stdout=output)
        self.assertEqual((ProbeDefinition.objects.count(),ClinicalGoal.objects.count(),ParentCoaching.objects.count()),(4,2,6))
        self.assertEqual(set(ParentCoaching.objects.values_list('instruction_language',flat=True)),{'fr','en','ar'})
        self.assertEqual(ProbeReview.objects.count(),0)
        self.assertFalse(ClinicalGoal.objects.get(pk=first_goal.pk).active)
        self.assertFalse(ParentCoaching.objects.filter(understanding_checked=True).exists())
        self.assertFalse(ClinicalGoal.objects.filter(external_assessment_status='confirmed').exists())
        self.assertTrue(all(not row.ready and row.state=='draft' for row in ProbeDefinition.objects.all()))
        with override_settings(DEMO_MODE=False), self.assertRaises(CommandError):
            call_command('seed_followup_demo',stdout=output)

    def test_goal_reloads_and_freezes_linked_draft_reserves_before_administration(self):
        probe = definition(self)
        stale_reference = ProbeDefinition.objects.get(pk=probe.pk)
        current = copy.deepcopy(probe.items)
        current[1]['word'] = 'new reserved word'
        update_definition(self.pro,probe,{'items':current})
        objective = goal(self,stale_reference)
        self.assertEqual(objective.reserved_words,['new reserved word'])
        self.assertEqual(reserved_words_for(self.child,self.variety),{'new reserved word'})
        probe.refresh_from_db()
        changed = copy.deepcopy(probe.items);changed[1]['word']='unprotected replacement'
        with self.assertRaises(ValidationError): update_definition(self.pro,probe,{'items':changed})
        probe.refresh_from_db();self.assertEqual(probe.items,current)
        self.assertEqual(ProbeAdministration.objects.count(),0)
        cloned = clone_definition(self.pro,probe)
        update_definition(self.pro,cloned,{'items':changed})
        self.assertEqual(reserved_words_for(self.child,self.variety),{'new reserved word'})
        probe.refresh_from_db();self.assertEqual(probe.items,current)

    def test_variant_identifier_conflicts_fail_before_snapshot_and_identical_variants_work(self):
        probe = definition(self)
        objective = goal(self,probe)
        objective.accepted_variants=[{'id':'regional','label':'Different clinical meaning','ipa':'/b/'}]
        objective.save()
        with self.assertRaises(ValidationError): start(self,probe,objective)
        self.assertEqual(ProbeAdministration.objects.count(),0)
        objective.accepted_variants=copy.deepcopy(probe.items[0]['accepted_variants']);objective.save()
        admin=start(self,probe,objective)
        for row in probe.items: save_rating(self.pro,admin,row['id'],rating('VARIANT_ACCEPTABLE'))
        finished=finalize_administration(self.pro,admin)
        self.assertEqual(professional_report(self.pro,finished)['groups'][0]['numerator'],2)
        self.assertEqual(admin.snapshot['goal']['accepted_variants'],admin.snapshot['items'][0]['accepted_variants'])


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class FollowupConcurrencyTests(TransactionTestCase):
    def setUp(self):
        install_fixture(self)
        self.probe = definition(self)
        self.goal = goal(self, self.probe)
        self.admin = start(self, self.probe, self.goal)
        for i in self.probe.items:
            save_rating(self.pro,self.admin,i['id'],rating())

    def worker(self, function):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            return function()
        finally:
            connections.close_all()

    def test_concurrent_finalization_has_one_immutable_result(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.worker,lambda:finalize_administration(self.pro,self.admin)) for _ in range(2)]
            rows=[f.result(timeout=12) for f in futures]
        self.assertEqual(rows[0].finalized_at,rows[1].finalized_at)
        self.assertEqual(rows[0].summary_snapshot,rows[1].summary_snapshot)
        self.assertEqual(ProbeAdministration.objects.filter(status='finalized').count(),1)

    def test_concurrent_clones_from_different_source_versions_are_unique(self):
        newer=clone_definition(self.pro,self.probe)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.worker,lambda source=source:clone_definition(self.pro,source)) for source in [self.probe,newer]]
            versions=[f.result(timeout=12).version for f in futures]
        self.assertEqual(set(versions),{3,4})
        self.assertEqual(ProbeDefinition.objects.filter(series=self.probe.series).count(),4)
