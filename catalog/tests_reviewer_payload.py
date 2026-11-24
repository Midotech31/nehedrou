"""Scoped exact-data presentation only; no real review or approval is created."""
import uuid
from django.contrib.auth.models import AnonymousUser
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.html import escape
from catalog.models import Activity, Review, Variety
from catalog.reviewer_payload import reviewer_payload
from catalog import tests_reviewer_guidance as guidance_tests
from core.models import AuditEvent
from qualification.models import EvidenceDocument


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ReviewerPayloadTests(TestCase):
    setUpTestData = classmethod(guidance_tests.ReviewerExperienceGuidanceTests.setUpTestData.__func__)
    setUp = guidance_tests.ReviewerExperienceGuidanceTests.setUp

    def page(self):
        return self.client.get(reverse('editorial_detail', args=[self.activity.pk]))

    def evidence(self, *, variety=None, category='familiarity', validity='unlimited', revoked=False):
        return EvidenceDocument.objects.create(variety=variety or self.variety, category=category,
            title='PRIVATE_TITLE_DO_NOT_RENDER', provenance='PRIVATE_PROVENANCE_DO_NOT_RENDER',
            uploaded_by=self.editor, file=ContentFile(b'Fictional evidence only', name=uuid.uuid4().hex+'.txt'),
            validity=validity, revoked=revoked, revocation_reason='Fictional withdrawal' if revoked else '')

    def structured(self, proof=None):
        self.activity.requested_target='b'
        self.activity.item_metadata={
            'a': {'meaning':'FIRST_RECORDED_MEANING', 'segments':['p','a'],
                  'target_occurrences':[{'index':0,'phoneme':'p','position':'initial'}],
                  'accepted_variants':[{'ipa':'/p-a/', 'reason':'RECORDED_VARIANT_REASON', 'hidden':'VARIANT_SECRET'}],
                  'familiarity': {'note':'RECORDED_FAMILIARITY_NOTE', **(proof or {}), 'hidden':'FAMILIARITY_SECRET'},
                  'hidden':'WORD_SECRET'},
            'b': {'meaning':'SECOND_RECORDED_MEANING', 'segments':['b','a'],
                  'target_occurrences':[{'index':0,'phoneme':'b','position':'initial'}], 'accepted_variants':[]}}
        self.activity.save()

    def test_structured_words_target_and_current_reference_are_visible_without_writes(self):
        document=self.evidence()
        self.structured({'evidence':str(document.pk),'sha256':document.sha256})
        digest=self.activity.fingerprint()
        counts=(Review.objects.count(), AuditEvent.objects.count(), Activity.objects.count(), EvidenceDocument.objects.count())
        response=self.page()
        self.assertEqual(response.status_code,200)
        for text in ['FIRST_RECORDED_MEANING','SECOND_RECORDED_MEANING','RECORDED_VARIANT_REASON',
                     'RECORDED_FAMILIARITY_NOTE', 'data-review-word="a"','data-review-word="b"',
                     'data-response-mode="matching"','data-requested-target="b"', 'data-familiarity-status="current"',
                     'start="0"','value="0"', 'lang="und-fonipa" dir="ltr"', document.sha256, str(document.pk), digest]:
            self.assertContains(response,text)
        for secret in ['PRIVATE_TITLE_DO_NOT_RENDER','PRIVATE_PROVENANCE_DO_NOT_RENDER','VARIANT_SECRET','FAMILIARITY_SECRET','WORD_SECRET']:
            self.assertNotContains(response,secret)
        self.assertContains(response,'class="table-scroll"',count=2)
        self.assertContains(response,reverse('qualification:evidence_file',args=[document.pk]))
        self.assertEqual(response.context['form']['expected_digest'].value(),digest)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.fingerprint(),digest)
        self.assertEqual((Review.objects.count(), AuditEvent.objects.count(), Activity.objects.count(), EvidenceDocument.objects.count()),counts)

    def test_half_filled_legacy_entries_remain_explicit_and_escaped(self):
        self.activity.item_metadata={'a':{'meaning':'<em>Legacy meaning</em>', 'familiarity':'Legacy authored note'}, 'b':{}}
        self.activity.save()
        response=self.page()
        self.assertContains(response,escape('<em>Legacy meaning</em>'))
        self.assertNotContains(response,'<em>Legacy meaning</em>')
        self.assertContains(response,'Legacy authored note')
        self.assertContains(response,'Not recorded')
        self.assertContains(response,'data-familiarity-status="missing"',count=2)
        self.assertEqual(Review.objects.count(),0)

    def test_task_modes_distinguish_fixed_random_and_no_requested_picture(self):
        for mode,target,state in [('matching','a','a'),('matching','','random'),('free','','none'),('observation','','none')]:
            with self.subTest(mode=mode,target=target):
                self.activity.response_mode=mode;self.activity.requested_target=target;self.activity.save()
                response=self.page()
                self.assertContains(response,'data-response-mode="'+mode+'"')
                self.assertContains(response,'data-requested-target="'+state+'"')
        Activity.objects.filter(pk=self.activity.pk).update(response_mode='legacy-unknown',requested_target='z')
        response=self.page()
        self.assertContains(response,'data-response-mode="unknown"')
        self.assertContains(response,'data-requested-target="unknown"')
        self.assertContains(response,'Unknown stored task value.')

    def test_reference_states_do_not_silently_repair_or_qualify_evidence(self):
        scenarios=[('fingerprint_missing',{},'unlimited',False,False),
                   ('fingerprint_mismatch',{'sha256':'0'*64},'unlimited',False,False),
                   ('revoked',None,'unlimited',True,False),
                   ('bytes_changed',None,'unlimited',False,True),
                   ('validity_unknown',None,'unknown',False,False)]
        for state,extra,validity,revoked,delete in scenarios:
            with self.subTest(state=state):
                document=self.evidence(validity=validity,revoked=revoked)
                proof={'evidence':str(document.pk), **({'sha256':document.sha256} if extra is None else extra)}
                self.structured(proof)
                if delete: document.file.storage.delete(document.file.name)
                response=self.page()
                self.assertContains(response,'data-familiarity-status="'+state+'"')
                if revoked or delete:
                    self.assertNotContains(response,reverse('qualification:evidence_file',args=[document.pk]))
                self.activity.refresh_from_db()
                self.assertEqual(self.activity.item_metadata['a']['familiarity'].get('sha256'),proof.get('sha256'))
        self.assertEqual(Review.objects.count(),0)

    def test_foreign_wrong_category_missing_and_malformed_references_leak_no_identifiers(self):
        documents=[self.evidence(variety=self.foreign_variety),self.evidence(category='rights')]
        for reference,sha in [(str(d.pk),d.sha256) for d in documents]+[(str(uuid.uuid4()),'a'*64),('MALFORMED_REFERENCE_MARKER','HIDDEN_INVALID_SHA')]:
            with self.subTest(reference=reference):
                self.structured({'evidence':reference,'sha256':sha})
                response=self.page()
                self.assertContains(response,'data-familiarity-status="unavailable"')
                self.assertNotContains(response,reference)
                self.assertNotContains(response,sha)
                self.assertNotContains(response,'PRIVATE_PROVENANCE_DO_NOT_RENDER')

    def test_editorial_read_boundaries_and_reusable_include_fail_closed(self):
        self.structured()
        for user in [self.foreign,self.ordinary]:
            self.client.force_login(user)
            self.assertEqual(self.page().status_code,404)
            self.assertIsNone(reviewer_payload(self.activity,user))
        self.client.logout()
        self.assertEqual(self.page().status_code,302)
        self.assertIsNone(reviewer_payload(self.activity,AnonymousUser()))
        self.client.force_login(self.editor)
        self.assertContains(self.page(),'data-reviewer-payload')
        self.assertEqual(Review.objects.count(),0)

    def test_labels_are_translated_and_arabic_words_keep_their_direction(self):
        from catalog.models import EditorialGrant
        variety=Variety.objects.create(code='ar-dz-pilot',language='ar',label='Synthetic Arabic fixture')
        EditorialGrant.objects.create(user=self.reviewer,variety=variety,linguistic_review=True)
        self.activity.variety=variety;self.activity.word_a='باب';self.activity.word_b='مفتاح';self.activity.save()
        self.structured()
        expected={'en':'Recorded task and word definitions','fr':'Tâche et définitions des mots enregistrées','ar':'المهمة وتعريفات الكلمات المسجّلة'}
        for language,title in expected.items():
            with self.subTest(language=language),translation.override(language):
                response=self.page()
                self.assertContains(response,title)
                self.assertContains(response,'lang="ar-DZ" dir="rtl">باب')
                self.assertContains(response,'lang="und-fonipa" dir="ltr"')
                self.assertContains(response,'data-review-word="a"')
