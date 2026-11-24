"""Public examples stay stateless and distinguish spoken Arabic varieties."""
from unittest.mock import patch
from django.conf import settings
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse
from catalog.content_catalog import public_example


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class PublicDemoVarietyTests(SimpleTestCase):
    # Any ORM access fails here: these are interface examples, not assignments.
    varieties = ('ar-msa-pilot', 'ar-dz-pilot')
    answer = {'answer': 'a', 'completion': 'completed', 'parent_report': 'easy'}

    def test_existing_default_words_are_preserved(self):
        for language, variety, words in [
            ('fr', 'fr-fr-pilot', ('chat', 'rat')),
            ('en', 'en-us-general-pilot', ('coat', 'goat')),
            ('ar', 'ar-dz-pilot', ('دار', 'نار')),
        ]:
            with self.subTest(language=language):
                response = self.client.get(f'/{language}/try/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['sample_variety_code'], variety)
                self.assertEqual((response.context['word_a'], response.context['word_b']), words)
                self.assertContains(response, f'name="next" value="/{language}/try/?variety={variety}"')

    def test_arabic_samples_have_distinct_words_language_and_matching_guide(self):
        for variety, words, word_language, images in [
            ('ar-msa-pilot', ('قط', 'كلب'), 'ar', ('editorial/cat.svg', 'editorial/dog.svg')),
            ('ar-dz-pilot', ('دار', 'نار'), 'ar-DZ', ('editorial/house.svg', 'editorial/fire.svg')),
        ]:
            with self.subTest(variety=variety):
                response = self.client.get('/ar/try/', {'variety': variety})
                self.assertEqual(response.status_code, 200)
                self.assertEqual((response.context['word_a'], response.context['word_b']), words)
                self.assertEqual((response.context['image_a'], response.context['image_b']), images)
                self.assertEqual(response.context['word_language'], word_language)
                row = public_example('ar', variety)
                self.assertEqual(row['variety_code'], variety)
                self.assertEqual((row['word_a'], row['word_b']), words)
                self.assertEqual(response.context['sample_guide'], {**row['practice_guide']['ar'], 'language': 'ar'})
                self.assertContains(response, f'lang="{word_language}"')
                self.assertContains(response, 'dir="rtl"')
                self.assertContains(response, 'data-activity-step=', count=3)
                for code in self.varieties:
                    self.assertContains(response, 'href="/ar/try/?variety=' + code + '"')
                self.assertNotContains(response, 'data-device-voice')
                self.assertNotContains(response, '<audio')

    def test_interface_language_is_independent_from_both_arabic_samples(self):
        for language in ['fr', 'en', 'ar']:
            for variety in self.varieties:
                with self.subTest(language=language, variety=variety):
                    response = self.client.get(f'/{language}/try/', {'variety': variety})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context['sample_variety_code'], variety)
                    self.assertEqual(response.context['guide_language'], language)
                    row = public_example(language, variety)
                    self.assertEqual(response.context['sample_guide'], {**row['practice_guide'][language], 'language': language})
                    self.assertContains(response, f'<html lang="{language}"')
                    self.assertContains(response, f'name="variety" value="{variety}"')

    def test_post_and_retry_preserve_exact_spoken_variety(self):
        for variety in self.varieties:
            response = self.client.post('/en/try/?variety=' + variety, {**self.answer, 'variety': variety})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'This is how a practice report is presented')
            self.assertEqual(response.context['sample_variety_code'], variety)
            self.assertContains(response, 'href="/en/try/?variety=' + variety + '"')
            self.assertNotContains(response, 'data-guided-activity')
            retry = self.client.get(response.context['demo_retry_url'])
            self.assertIsNone(retry.context['summary'])
            self.assertEqual(retry.context['sample_variety_code'], variety)
            self.assertFalse(retry.context['form'].is_bound)

    def test_form_error_keeps_variety_and_caregiver_response(self):
        for variety in self.varieties:
            response = self.client.post('/ar/try/', {'variety': variety, 'completion': 'completed', 'parent_report': 'difficult'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['sample_variety_code'], variety)
            self.assertIn('answer', response.context['form'].errors)
            self.assertEqual(response.context['form']['parent_report'].value(), 'difficult')
            self.assertContains(response, f'name="variety" value="{variety}"')

    def test_explicit_variety_change_starts_a_new_unbound_example(self):
        self.client.post('/ar/try/', {**self.answer, 'variety': 'ar-dz-pilot'})
        response = self.client.get('/ar/try/', {'variety': 'ar-msa-pilot'})
        self.assertIsNone(response.context['summary'])
        self.assertFalse(response.context['form'].is_bound)
        self.assertEqual(response.context['sample_variety_code'], 'ar-msa-pilot')
        self.assertNotIn(settings.SESSION_COOKIE_NAME, self.client.cookies)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_unknown_empty_and_duplicate_get_varieties_are_rejected(self):
        for query in ['variety=unknown', 'variety=', 'variety=ar-dz-pilot&variety=ar-msa-pilot']:
            response = self.client.get('/en/try/?' + query)
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, 'Choose a supported spoken variety for this sample.', status_code=400)
            self.assertContains(response, 'action="/en/try/?variety=en-us-general-pilot"', status_code=400)
            self.assertIsNone(response.context['summary'])
            self.assertIn('no-store', response.headers['Cache-Control'])

    def test_unknown_duplicate_and_conflicting_post_varieties_never_create_summary(self):
        for url, extra in [
            ('/en/try/', {'variety': 'unknown'}),
            ('/en/try/', {'variety': ''}),
            ('/en/try/', {'variety': ['ar-msa-pilot', 'ar-dz-pilot']}),
            ('/en/try/?variety=ar-msa-pilot', {'variety': 'ar-dz-pilot'}),
        ]:
            response = self.client.post(url, {**self.answer, **extra})
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(response.context['summary'])
            self.assertNotContains(response, 'This is how a practice report is presented', status_code=400)

    def test_stopped_samples_do_not_count_an_answer_or_accept_private_text(self):
        for variety in self.varieties:
            response = self.client.post('/en/try/', {'variety': variety, 'answer': 'b', 'completion': 'stopped',
                'parent_report': 'help', 'comment': 'PRIVATE-TEXT', 'child': 'private-child', 'ticket': 'private-ticket'})
            self.assertContains(response, 'Stopped · no answer counted')
            for text in ['PRIVATE-TEXT', 'private-child', 'private-ticket', 'A different picture selected']:
                self.assertNotContains(response, text)
            self.assertNotIn(settings.SESSION_COOKIE_NAME, self.client.cookies)

    def test_each_sample_requires_csrf_for_post(self):
        client = Client(enforce_csrf_checks=True)
        for variety in self.varieties:
            url = '/ar/try/?variety=' + variety
            data = {**self.answer, 'variety': variety}
            self.assertEqual(client.post(url, data).status_code, 403)
            client.get(url)
            token = client.cookies[settings.CSRF_COOKIE_NAME].value
            self.assertEqual(client.post(url, {**data, 'csrfmiddlewaretoken': token}).status_code, 200)

    @override_settings(DEMO_MODE=False)
    def test_both_samples_remain_unavailable_outside_demo_mode(self):
        for variety in self.varieties:
            url = '/ar/try/?variety=' + variety
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {**self.answer, 'variety': variety}).status_code, 404)

    def test_language_switch_keeps_selected_variety_even_from_default_page(self):
        response = self.client.get('/ar/try/')
        next_url = response.context['language_next_url']
        response = self.client.post(reverse('set_language'), {'language': 'en', 'next': next_url})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/en/try/?variety=ar-dz-pilot')
        page = self.client.get(response.url)
        self.assertEqual(page.context['sample_variety_code'], 'ar-dz-pilot')
        self.assertEqual(page.context['word_language'], 'ar-DZ')
        self.assertEqual(page.context['guide_language'], 'en')

    def test_missing_exact_msa_example_never_falls_back_to_darja_guide(self):
        with patch('catalog.content_catalog.public_arabic_definitions', return_value=[]):
            self.assertIsNone(public_example('ar', 'ar-msa-pilot'))
            response = self.client.get('/ar/try/?variety=ar-msa-pilot')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['sample_guide'], {})
            self.assertEqual(response.context['sample_sources'], [])
            self.assertEqual(response.context['word_a'], 'قط')
