"""Formal pair checks are safeguards, never human clinical validation."""
import copy
import json
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from catalog.content_validation import validate_minimal_pair, validate_content_guide

class ProposedArabicPairTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows=json.loads((Path(settings.BASE_DIR)/'docs/arabic-library-v1.json').read_text(encoding='utf-8'))['activities']

    def test_ten_standard_pairs_have_one_phoneme_difference_at_the_documented_position(self):
        pairs=[row for row in self.rows if row['kind']=='phonological_contrast']
        self.assertEqual(len(pairs),10)
        for row in pairs:
            with self.subTest(title=row['title']):
                self.assertEqual(row['variety_code'],'ar-msa-pilot')
                validate_minimal_pair(row['item_metadata'],row['response_mode'])
                self.assertFalse(row['is_demo'])
                self.assertEqual(row['state'],'draft')
                self.assertTrue(row['evidence_sources'])
        medial=[row for row in pairs if row['word_a']=='قَلَم'][0]
        self.assertEqual(medial['item_metadata']['a']['target_occurrences'],[{'index':2,'phoneme':'l','position':'medial'}])

    def test_homophones_multiple_changes_and_wrong_target_cannot_claim_minimality(self):
        source=next(row for row in self.rows if row['kind']=='phonological_contrast')['item_metadata']
        homophones=copy.deepcopy(source);homophones['b']=copy.deepcopy(homophones['a'])
        multiple=copy.deepcopy(source);multiple['b']['segments'][-1]='t'
        wrong_target=copy.deepcopy(source)
        for item in wrong_target.values():
            item['target_occurrences']=[{'index':1,'phoneme':item['segments'][1],'position':'medial'}]
        for metadata in [homophones,multiple,wrong_target]:
            with self.subTest(metadata=metadata),self.assertRaises(ValidationError):
                validate_minimal_pair(metadata,'matching')
        with self.assertRaises(ValidationError):
            validate_minimal_pair(source,'free')

    def test_lexical_and_communicative_darja_does_not_invent_ipa_or_minimal_pairs(self):
        rows=[row for row in self.rows if row['variety_code']=='ar-dz-pilot']
        self.assertEqual(len(rows),32)
        for row in rows:
            self.assertNotEqual(row['kind'],'phonological_contrast')
            self.assertFalse(row['transcription_a']);self.assertFalse(row['transcription_b'])
            self.assertFalse(row['audio_a']);self.assertFalse(row['audio_b'])
            for item in row['item_metadata'].values():
                self.assertEqual(item['segments'],[])
                self.assertEqual(item['accepted_variants'],[])
                self.assertTrue(item['family_word_candidates'])

    def test_every_guide_has_three_languages_and_reference_scope_without_approval(self):
        for row in self.rows:
            self.assertEqual(set(row['practice_guide']),{'fr','en','ar'})
            self.assertEqual(set(row['instructions']),{'fr','en','ar'})
            validate_content_guide(row['practice_guide'],row['evidence_sources'])
            if row['response_mode']!='matching':
                self.assertEqual(row['requested_target'],'')
