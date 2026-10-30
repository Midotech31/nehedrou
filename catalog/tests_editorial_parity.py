"""Editorial parity checks do not substitute for competent human review."""
import copy
import hashlib
import io
import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from catalog.content_validation import validate_content_guide, validate_minimal_pair
from catalog.models import Activity, EditorialGrant, Review, Variety
from core.models import AuditEvent, User


def documents():
    root = Path(settings.BASE_DIR)
    source = json.loads((root/'docs/arabic-library-v1.json').read_text(encoding='utf-8'))
    matrix = json.loads((root/'docs/msa-editorial-parity-20261030.json').read_text(encoding='utf-8'))
    return source, matrix


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class EditorialParityTests(SimpleTestCase):
    def test_matrix_covers_exactly_ten_unapproved_series_without_linguistic_changes(self):
        source, matrix = documents()
        pairs = {row['series']:row for row in source['activities'] if row['kind']=='phonological_contrast'}
        self.assertEqual(len(pairs), 10)
        self.assertEqual(set(pairs), {row['series'] for row in matrix['activities']})
        for entry in matrix['activities']:
            row = pairs[entry['series']]
            self.assertEqual((row['state'],row['is_demo']), ('draft',False))
            self.assertEqual(digest({field:row[field] for field in matrix['identity_fields']}), entry['linguistic_identity_sha256'])
            self.assertEqual(digest(entry['previous_guide']), entry['previous_guide_sha256'])
            validate_minimal_pair(row['item_metadata'],row['response_mode'])
            validate_content_guide(row['practice_guide'], row['evidence_sources'])
            for language in ('fr','en','ar'):
                self.assertEqual(entry['human_reviews'][language], {'status':'pending_competent_review','reviewer':None,'reviewed_at':None})
                self.assertEqual(len(row['practice_guide'][language]['limits']),4)
                for requirement in entry['required_information']:
                    text = requirement['prepared_text'][language]
                    self.assertTrue(text)
                    self.assertIn(text, json.dumps(row['practice_guide'][language],ensure_ascii=False))
        baseline = json.loads((Path(settings.BASE_DIR)/'docs/catalog-candidates.json').read_text(encoding='utf-8'))
        self.assertFalse(set(pairs) & {row['series'] for row in baseline})

    def test_precise_cautions_survive_in_all_three_languages(self):
        source, _matrix = documents()
        anchors = {
            'تِين':('/tˤ/','/iː/','تين / طين'),
            'قَلَم':('2','ق'),
            'بَيْت':('/aj/','/a/','/j/','بيت / بيض'),
            'رَمْل':('نملة','نمل'),
            'شَمْعَة':('/a/','[h]','/at/','شمعة / دمعة'),
            'تُوت':('/uː/','حوت'),
            'دَار':('/aː/',),
            'جَرَس':('/dʒ/','حصان','فرس'),
            'جَمَل':('/ħamal/','/ħaml/','خروف','/dʒ/'),
        }
        for row in source['activities']:
            if row['word_a'] not in anchors:
                continue
            for language in ('fr','en','ar'):
                text = ' '.join(row['practice_guide'][language]['limits'])
                for anchor in anchors[row['word_a']]:
                    self.assertIn(anchor,text,(row['word_a'],language,anchor))
        lamb = next(row for row in source['activities'] if row['word_a']=='جَمَل')
        for language,word in [('fr','adulte'),('en','adult'),('ar','البالغ')]:
            self.assertIn(word,' '.join(lamb['practice_guide'][language]['limits']))
        heart = next(row for row in source['activities'] if row['word_a']=='كَلْب')
        for language,word in [('fr','organe'),('en','organ'),('ar','عضو')]:
            self.assertIn(word,' '.join(heart['practice_guide'][language]['limits']))

    def test_arabic_phoneme_lists_are_not_labelled_syllables(self):
        source,_matrix=documents()
        for row in source['activities']:
            if row['kind']=='phonological_contrast':
                text=' '.join(row['practice_guide']['ar']['listen'])
                self.assertIn('فونيمات',text)
                self.assertNotIn('المقاطع الصوتية',text)
        key=None
        entries={}
        for line in (Path(settings.BASE_DIR)/'locale/ar/LC_MESSAGES/django.po').read_text(encoding='utf-8').splitlines():
            if line.startswith('msgid '): key=json.loads(line[6:])
            elif line.startswith('msgstr '): entries[key]=json.loads(line[7:])
        for key in ['Ordered phoneme segments','Segments must be an ordered list of phonemes.','Phonemes in order','Separate phonemes with spaces. Example: d a r.']:
            self.assertIn('فونيم',entries[key])
            self.assertNotIn('مقاطع',entries[key])


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class GuideRevisionCommandTests(TestCase):
    def setUp(self):
        self.source,self.matrix=documents()
        self.row=next(row for row in self.source['activities'] if row['kind']=='phonological_contrast')
        entry=next(row for row in self.matrix['activities'] if row['series']==self.row['series'])
        self.variety=Variety.objects.create(code='ar-msa-pilot',language='ar',label='Fictional MSA')
        self.actor=User.objects.create_user(username='parity-editor',email='parity@example.test')
        self.outsider=User.objects.create_user(username='parity-outsider',email='outsider@example.test')
        EditorialGrant.objects.create(user=self.actor,variety=self.variety,edit=True,clinical_review=True)
        values=copy.deepcopy(self.row)
        values.pop('variety_code')
        values['practice_guide']=entry['previous_guide']
        values['state']='review'
        self.original=Activity.objects.create(variety=self.variety,**values)
        self.review=Review.objects.create(activity=self.original,reviewer=self.actor,kind='clinical',approved=False,note='Fictional negative review remains historical.')

    def invoke(self,**kwargs):
        output=io.StringIO()
        call_command('prepare_msa_guide_revisions',actor=self.actor.username,stdout=output,**kwargs)
        return output.getvalue()

    def test_default_dry_run_has_no_writes_and_requires_authorized_actor(self):
        before=(Activity.objects.count(),Review.objects.count(),AuditEvent.objects.count())
        self.assertIn('WOULD_CREATE',self.invoke())
        self.assertEqual((Activity.objects.count(),Review.objects.count(),AuditEvent.objects.count()),before)
        with self.assertRaises(CommandError):
            call_command('prepare_msa_guide_revisions',actor=self.outsider.username,apply=True,stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command('prepare_msa_guide_revisions',apply=True,stdout=io.StringIO())
        self.assertEqual(Activity.objects.count(),1)

    def test_explicit_apply_creates_new_draft_without_copying_reviews_or_rewriting_history(self):
        before=self.original.fingerprint()
        self.assertIn('1 new drafts',self.invoke(apply=True))
        self.original.refresh_from_db()
        self.assertEqual(self.original.fingerprint(),before)
        self.assertEqual(self.original.state,'review')
        self.review.refresh_from_db()
        self.assertEqual(self.review.activity_id,self.original.pk)
        newest=Activity.objects.filter(series=self.original.series).latest('version')
        self.assertEqual((newest.version,newest.state,newest.is_demo),(2,'draft',False))
        self.assertEqual(newest.practice_guide,self.row['practice_guide'])
        self.assertEqual(newest.item_metadata,self.original.item_metadata)
        self.assertFalse(newest.reviews.exists())
        self.assertFalse(newest.usable)
        self.assertTrue(AuditEvent.objects.filter(actor=self.actor,action='catalog.guide_revision_prepared',object_id=str(newest.pk)).exists())
        self.assertIn('0 new drafts',self.invoke(apply=True))
        self.assertEqual(Activity.objects.count(),2)

    def test_existing_editorial_work_is_preserved_for_manual_review(self):
        self.original.practice_guide['en']['limits'][0]='Fictional distinct editorial work; preserve it.'
        self.original.save()
        self.assertIn('MANUAL',self.invoke(apply=True))
        self.assertEqual(Activity.objects.count(),1)
        self.original.refresh_from_db()
        self.assertIn('preserve it',self.original.practice_guide['en']['limits'][0])

    def test_old_published_program_reference_survives_a_new_draft_revision(self):
        # Simulate a persisted historical reference; this test grants no approval.
        from care.models import Child, Program, ProgramItem
        from core.models import Membership, Organization
        from qualification.models import AvailabilityDecision
        Activity.objects.filter(pk=self.original.pk).update(state='published')
        self.original.refresh_from_db()
        organization=Organization.objects.create(name='Fictional historical reference')
        Membership.objects.create(organization=organization,user=self.actor,role='owner')
        child=Child.objects.create(organization=organization,responsible=self.actor,code='Historical fictional child',age_years=5)
        child.varieties.add(self.variety)
        program=Program.objects.create(organization=organization,child=child,variety=self.variety,created_by=self.actor,title='Historical fictional assignment')
        # Materialize a legacy row directly; current assignment validation correctly refuses this unqualified fixture.
        item=ProgramItem(program=program,activity=self.original)
        ProgramItem.objects.bulk_create([item])
        original_digest=self.original.fingerprint()
        self.invoke(apply=True)
        self.original.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.original.state,'published')
        self.assertEqual(self.original.fingerprint(),original_digest)
        self.assertEqual(item.activity_id,self.original.pk)
        self.assertEqual(item.activity.version,1)
        self.assertEqual(Activity.objects.get(series=self.original.series,version=2).state,'draft')
        self.assertFalse(Review.objects.filter(approved=True).exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
