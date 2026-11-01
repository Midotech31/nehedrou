import hashlib
import json
import tempfile
import uuid
from datetime import date, timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,override_settings
from django.urls import reverse
from catalog.models import Activity, Variety, EditorialGrant, Review, MediaAsset
from catalog.readiness import activity_readiness,snapshot_media
from catalog.services import transition,review_version,clone_version
from core.models import User
from .models import EvidenceDocument,ReviewerCompetence,ReviewerCompetenceDecision,AvailabilityDecision,LexicalPack,LexicalCandidate,FamiliarityStudy,PackReview
from .services import availability_for,evidence_snapshot,REQUIRED_EVIDENCE,change_pack_state,clone_pack,has_competence,record_competence_decision
from .test_support import evidence_fixture,competence_fixture,media_fixture,prepare_activity_fixture,availability_fixture

@override_settings(DEMO_MODE=False,MFA_REQUIRED=False)
class DocumentaryQualificationTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage=override_settings(MEDIA_ROOT=self.directory.name)
        self.storage.enable();self.addCleanup(self.storage.disable)
        self.variety=Variety.objects.create(code='ar-local-test',language='ar',label='Fictional local variety')
        self.actor=User.objects.create_user(username='clinical',email='clinical@fictional.example',password='Fictional-Test-2026!')
        self.other=User.objects.create_user(username='linguistic',email='linguistic@fictional.example',password='Fictional-Test-2026!')
        competence_fixture(self.actor,self.variety,'clinical');competence_fixture(self.other,self.variety,'linguistic')

    def activity(self):
        return Activity.objects.create(variety=self.variety,series=uuid.uuid4(),title='Fictional contrast',contrast='p/b',word_a='pa',word_b='ba',instructions={'fr':'Fictif','en':'Fictional','ar':'مثال وهمي'},population='Fictional target',rights='Fictional only',is_demo=False)

    def test_permission_does_not_create_competence_and_changes_request_allowed(self):
        unqualified=User.objects.create_user(username='unqualified',email='unqualified@fictional.example',password='Fictional-Test-2026!')
        EditorialGrant.objects.create(user=unqualified,variety=self.variety,clinical_review=True)
        activity=self.activity();activity.state='review';activity.save()
        review_version(unqualified,activity,'clinical',False,'Needs qualified review')
        with self.assertRaises(ValidationError):
            review_version(unqualified,activity,'clinical',True,'Permission is not expertise')
        self.assertEqual(activity.reviews.count(),1)

    def test_review_approval_requires_a_current_independent_competence_check(self):
        declaration=ReviewerCompetence.objects.get(user=self.actor,variety=self.variety,discipline='clinical')
        declaration.professional_role='Fictional SLP'
        declaration.experience='Fictional regional experience'
        declaration.save()
        self.assertFalse(has_competence(self.actor,self.variety,'clinical'))
        activity=self.activity();activity.state='review';activity.save()
        with self.assertRaises(ValidationError):
            review_version(self.actor,activity,'clinical',True,'Fictional self-assertion')

        with self.assertRaises(ValidationError):
            record_competence_decision(self.actor,declaration.pk,'verified','Self-check is not permitted for this declaration.',date(2026,1,1),expected_digest=declaration.fingerprint())

        verifier=User.objects.create_user(username='variety-publisher',email='variety-publisher@fictional.example',password='Fictional-Test-2026!')
        with self.assertRaises(PermissionDenied):
            record_competence_decision(verifier,declaration.pk,'verified','Identity and regional competence checked using a fictional source.',date(2026,1,1),expected_digest=declaration.fingerprint())
        EditorialGrant.objects.create(user=verifier,variety=self.variety,publish=True)
        with self.assertRaises(ValidationError):
            record_competence_decision(verifier,declaration.pk,'verified','Fictional check cannot be dated in the future.',date.today()+timedelta(days=1),expected_digest=declaration.fingerprint())
        decision=record_competence_decision(verifier,declaration.pk,'verified','Identity and regional competence checked using a fictional source.',date(2026,1,1),expected_digest=declaration.fingerprint())
        self.assertEqual(decision.snapshot_digest,declaration.fingerprint())
        self.assertTrue(has_competence(self.actor,self.variety,'clinical'))

        declaration.experience='Edited after the independent verification.'
        declaration.save()
        self.assertFalse(has_competence(self.actor,self.variety,'clinical'))
        with self.assertRaises(ValidationError):
            ReviewerCompetenceDecision.objects.create(competence=declaration,snapshot_digest=decision.snapshot_digest,status='verified',checked_on=date(2026,1,1),basis='Fictional stale decision for an older declaration.',decided_by=verifier)

    def test_competence_decision_is_immutable_and_a_later_rejection_takes_effect(self):
        declaration=ReviewerCompetence.objects.get(user=self.actor,variety=self.variety,discipline='clinical')
        verifier=declaration.current_verification.decided_by
        decision=declaration.current_verification
        self.assertTrue(has_competence(self.actor,self.variety,'clinical'))
        with self.assertRaises(ValidationError):
            decision.basis='Altered historical check';decision.save()
        record_competence_decision(verifier,declaration.pk,'rejected','Fictional identity check failed on this date.',date(2026,1,2),expected_digest=declaration.fingerprint())
        self.assertFalse(has_competence(self.actor,self.variety,'clinical'))

    def test_verification_view_is_scoped_to_publishers_and_never_self_verifies(self):
        declaration=ReviewerCompetence.objects.get(user=self.other,variety=self.variety,discipline='linguistic')
        self.client.force_login(self.actor)
        index=self.client.get(reverse('qualification:competence_verification_index'))
        self.assertEqual(index.status_code,200)
        self.assertContains(index,'linguistic')
        self.assertEqual(self.client.get(reverse('qualification:competence_verification',args=[declaration.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('qualification:competence_verification',args=[ReviewerCompetence.objects.get(user=self.actor,variety=self.variety,discipline='clinical').pk])).status_code,404)
        declaration.experience+=' updated after the old check'
        declaration.save()
        path=reverse('qualification:competence_verification',args=[declaration.pk])
        invalid=self.client.post(path,{'expected_digest':declaration.fingerprint(),'status':'verified','checked_on':'2026-01-01','basis':'too short'})
        self.assertEqual(invalid.status_code,200)
        self.assertFalse(has_competence(self.other,self.variety,'linguistic'))
        accepted=self.client.post(path,{'expected_digest':declaration.fingerprint(),'status':'verified','checked_on':'2026-01-01','basis':'Fictional independent identity and variety check recorded.'})
        self.assertEqual(accepted.status_code,302)
        self.assertTrue(has_competence(self.other,self.variety,'linguistic'))
        outsider=User.objects.create_user(username='no-publish-scope',email='no-publish-scope@fictional.example',password='Fictional-Test-2026!')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse('qualification:competence_verification_index')).context['rows'],[])
        self.assertEqual(self.client.get(reverse('qualification:competence_verification',args=[declaration.pk])).status_code,404)

    def test_two_disciplines_from_same_person_cannot_publish(self):
        activity=self.activity();prepare_activity_fixture(activity,self.actor,self.other)
        competence_fixture(self.actor,self.variety,'linguistic')
        review_version(self.actor,activity,'linguistic',True,'Same person, separate discipline')
        self.assertFalse(activity.has_current_reviews())
        with self.assertRaises(ValidationError): transition(self.actor,activity.pk,'approved')
        review_version(self.other,activity,'linguistic',True,'Independent latest approval')
        self.assertTrue(activity.has_current_reviews())

    def test_exact_byte_hash_and_rights_changes_block_reviews_and_new_use(self):
        activity=self.activity();prepare_activity_fixture(activity,self.actor,self.other)
        self.assertTrue(activity.has_current_reviews())
        digest=activity.fingerprint()
        asset=MediaAsset.objects.get(pk=activity.audio_a.rstrip('/').split('/')[-1])
        asset.rights='Changed rights scope';asset.save()
        self.assertNotEqual(activity.fingerprint(),digest)
        self.assertFalse(activity.has_current_reviews())
        self.assertFalse(activity_readiness(activity)['ready'])
        asset.rights='Fictional test rights only';asset.save()
        self.assertEqual(activity.fingerprint(),digest)
        initial_manifest=dict(activity.media_manifest)
        with asset.file.storage.open(asset.file.name,'wb') as stream:stream.write(b'Replaced bytes')
        self.assertFalse(asset.intact)
        self.assertNotEqual(activity.fingerprint(),digest)
        self.assertFalse(activity.has_current_reviews())
        activity.refresh_from_db();self.assertEqual(activity.media_manifest,initial_manifest)

    def test_rights_proof_corruption_and_revocation_change_exact_content_fingerprint(self):
        activity=self.activity();prepare_activity_fixture(activity,self.actor,self.other)
        self.assertTrue(activity.has_current_reviews())
        digest=activity.fingerprint();initial_manifest=dict(activity.media_manifest)
        asset=MediaAsset.objects.get(pk=activity.audio_a.rstrip('/').split('/')[-1])
        proof=asset.rights_evidence
        with proof.file.storage.open(proof.file.name,'rb') as stream:original=stream.read()
        with proof.file.storage.open(proof.file.name,'wb') as stream:stream.write(b'Changed documentary bytes')
        self.assertNotEqual(activity.fingerprint(),digest)
        self.assertFalse(activity.has_current_reviews())
        self.assertFalse(activity_readiness(activity)['ready'])
        with proof.file.storage.open(proof.file.name,'wb') as stream:stream.write(original)
        self.assertEqual(activity.fingerprint(),digest)
        proof.revoked=True;proof.revocation_reason='Fictional rights revocation';proof.save()
        self.assertNotEqual(activity.fingerprint(),digest)
        self.assertFalse(activity.has_current_reviews())
        activity.refresh_from_db();self.assertEqual(activity.media_manifest,initial_manifest)

    def test_availability_requires_five_intact_evidence_and_revocation_prevails(self):
        version=self.activity().fingerprint()
        self.assertFalse(availability_for('practice',self.variety,version)['available'])
        with self.assertRaises(ValidationError):
            AvailabilityDecision.objects.create(module='practice',variety=self.variety,version=version,status='available',scope='Test',reason='Test',decided_by=self.actor)
        decision=availability_fixture('practice',self.variety,version,self.actor)
        self.assertTrue(availability_for('practice',self.variety,version)['available'])
        self.assertFalse(availability_for('practice',self.variety,'b'*64)['available'])
        doc=EvidenceDocument.objects.get(pk=decision.evidence['pilot']['id']);doc.revoked=True;doc.revocation_reason='Test revocation';doc.save()
        self.assertFalse(availability_for('practice',self.variety,version)['available'])
        with self.assertRaises(ValidationError): decision.reason='Edit historical decision';decision.save()
        AvailabilityDecision.objects.create(module='practice',variety=self.variety,version=version,status='revoked',scope='Same test scope',reason='Test revocation',decided_by=self.actor,target_snapshot=decision.target_snapshot)
        self.assertEqual(availability_for('practice',self.variety,version)['decision'].status,'revoked')

    def test_publication_and_real_use_are_separate_evidence_gates(self):
        activity=self.activity();prepare_activity_fixture(activity,self.actor,self.other)
        transition(self.actor,activity.pk,'approved');activity=transition(self.actor,activity.pk,'published')
        self.assertFalse(activity.usable)
        availability_fixture('practice',self.variety,activity.fingerprint(),self.actor)
        self.assertTrue(activity.usable)
        digest=activity.fingerprint()
        activity.word_a='Changed published word'
        with self.assertRaises(ValidationError):activity.save()
        activity.refresh_from_db();self.assertEqual(activity.fingerprint(),digest)
        clone=clone_version(self.actor,activity)
        self.assertEqual(clone.version,2);self.assertEqual(clone.state,'draft')
        self.assertFalse(clone.has_current_reviews())

    def test_private_evidence_is_not_shared_with_families_or_other_varieties(self):
        doc=evidence_fixture(self.variety,self.actor,'rights')
        outsider=User.objects.create_user(username='family',email='family@fictional.example',password='Fictional-Test-2026!')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse('qualification:evidence_file',args=[doc.pk])).status_code,404)
        self.client.force_login(self.actor)
        response=self.client.get(reverse('qualification:evidence_file',args=[doc.pk]));self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertEqual(b''.join(response.streaming_content),b'Fictional test evidence only')
        doc.revoked=True;doc.revocation_reason='Test';doc.save()
        self.assertEqual(self.client.get(reverse('qualification:evidence_file',args=[doc.pk])).status_code,404)

    def pack(self):
        return LexicalPack.objects.create(variety=self.variety,title='Fictional regional pack',series=uuid.uuid4(),region='Fictional region',scope='Fictional speech community',population='Already assessed, fictional only',indications='Professional choice',limits='No norms or efficacy claim',created_by=self.actor)

    def test_regional_pack_draft_exposes_missing_items_without_manufacturing_approval(self):
        pack=self.pack()
        candidate=LexicalCandidate.objects.create(pack=pack,word='دار',meaning='Fictional house',role='training',provenance='Working local hypothesis')
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(reverse('qualification:pack_detail',args=[pack.pk])).status_code,200)
        change_pack_state(self.actor,pack.pk,'review');pack.refresh_from_db()
        with self.assertRaises(ValidationError):PackReview.objects.create(pack=pack,reviewer=self.actor,kind='clinical',approved=True,note='Incomplete')
        PackReview.objects.create(pack=pack,reviewer=self.actor,kind='clinical',approved=False,note='Missing IPA, familiarity, audio and rights')
        with self.assertRaises(ValidationError):change_pack_state(self.actor,pack.pk,'published')
        self.assertEqual(pack.reviews.count(),1)
        with self.assertRaises(ValidationError):candidate.meaning='Edit submitted content';candidate.save()

    def test_complete_pack_reviews_exact_content_and_keeps_familiarity_denominators(self):
        pack=self.pack()
        candidate=LexicalCandidate.objects.create(pack=pack,word='دار',meaning='Fictional house',ipa='/dar/',segments=['d','a','r'],occurrences=[{'index':0,'phoneme':'d','position':'initial'}],role='reserved',provenance='Fictional lexical source',image=media_fixture(self.variety,self.actor,'image'),audio=media_fixture(self.variety,self.actor,'audio'))
        proof=evidence_fixture(self.variety,self.actor,'familiarity')
        with self.assertRaises(ValidationError):FamiliarityStudy.objects.create(candidate=candidate,method='Fictional exploratory test',participants=1,recognized=2,evidence=proof,recorded_by=self.actor)
        FamiliarityStudy.objects.create(candidate=candidate,method='Fictional exploratory test',participants=3,recognized=2,alternative_names=['Fictional synonym'],evidence=proof,recorded_by=self.actor)
        change_pack_state(self.actor,pack.pk,'review');pack.refresh_from_db()
        for user,kind in [(self.actor,'clinical'),(self.other,'linguistic')]:PackReview.objects.create(pack=pack,reviewer=user,kind=kind,approved=True,note='Fictional test approval')
        published=change_pack_state(self.actor,pack.pk,'published')
        clone=clone_pack(self.actor,published);self.assertEqual(clone.version,2);self.assertEqual(clone.candidates.count(),1);self.assertEqual(clone.reviews.count(),0)
        self.assertEqual(clone.candidates.first().familiarity.first().recognized,2)


    def test_candidate_form_converts_readable_segments_targets_and_variants(self):
        from .forms import CandidateForm, FamiliarityForm
        pack=self.pack()
        form=CandidateForm({'word':'دار','meaning':'Fictional house','ipa':'/dar/','role':'reserved','provenance':'Fictional regional attestation','segment_list':'d a r','target_list':'1 ; d ; initial','variant_list':'/daːr/ ; Fictional local option','synonym_list':'Fictional alternate'},instance=LexicalCandidate(pack=pack))
        self.assertTrue(form.is_valid(),form.errors)
        candidate=form.save()
        self.assertEqual(candidate.segments,['d','a','r'])
        self.assertEqual(candidate.occurrences,[{'index':0,'phoneme':'d','position':'initial'}])
        self.assertEqual(candidate.accepted_variants,[{'ipa':'/daːr/','reason':'Fictional local option'}])
        self.assertEqual(candidate.synonyms,['Fictional alternate'])
        form=CandidateForm({'word':'دار','meaning':'Test','role':'training','provenance':'Test','segment_list':'d a r','target_list':'4 ; r ; final'},instance=LexicalCandidate(pack=pack))
        self.assertFalse(form.is_valid())

    def test_inactive_reviewer_declaration_does_not_keep_a_live_approval(self):
        activity=self.activity();prepare_activity_fixture(activity,self.actor,self.other)
        self.assertTrue(activity.has_current_reviews())
        self.other.is_active=False;self.other.save()
        self.assertFalse(activity.has_current_reviews())

    def test_model_availability_cannot_be_recorded_without_publishing_authority(self):
        outsider=User.objects.create_user(username='unscoped',email='unscoped@fictional.example',password='Fictional-Test-2026!')
        with self.assertRaises(ValidationError):AvailabilityDecision.objects.create(module='practice',variety=self.variety,version='a'*64,status='blocked',scope='Test',reason='Unauthorised direct model attempt',decided_by=outsider)


    def test_noneditor_availability_is_read_only_and_contains_no_private_decisions(self):
        outsider=User.objects.create_user(username='status-family',email='status-family@fictional.example',password='Fictional-Test-2026!')
        # A raw historical row models the pre-binding migration state without inventing a target.
        AvailabilityDecision.objects.bulk_create([AvailabilityDecision(module='practice',variety=self.variety,version='a'*64,status='blocked',scope='PRIVATE-SCOPE-MARKER',reason='PRIVATE-DECISION-MARKER',decided_by=self.actor)])
        self.client.force_login(outsider)
        response=self.client.get(reverse('qualification:availability'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'PRIVATE-SCOPE-MARKER');self.assertNotContains(response,'PRIVATE-DECISION-MARKER')
        self.assertNotIn('decisions',response.context)
        self.assertEqual(self.client.post(reverse('qualification:availability'),{}).status_code,403)
        self.assertEqual(self.client.get(reverse('qualification:index')).status_code,403)
