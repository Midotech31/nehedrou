from django.test import Client, SimpleTestCase, override_settings


@override_settings(DEMO_MODE=True)
class PublicDemonstrationTests(SimpleTestCase):
    # SQL access is forbidden in this test class: the public preview must never
    # read child records or persist practice sessions.
    def test_preview_renders_in_all_interface_languages(self):
        for language, word in [('fr', 'chat'), ('en', 'cat'), ('ar', 'قِطّ')]:
            response = self.client.get(f'/{language}/try/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'lang="{language}"')
            self.assertContains(response, word)
            self.assertContains(response, 'data-activity-step=', count=3)
            self.assertNotContains(response, 'name="comment"')
            self.assertNotContains(response, 'name="ticket"')
            self.assertIn('no-store', response.headers['Cache-Control'])
            if language == 'ar':
                self.assertContains(response, 'dir="rtl"')

    def test_completed_choices_preview_without_accepting_identifiers(self):
        for answer, label in [('a', 'Matching picture selected'), ('b', 'A different picture selected')]:
            response = self.client.post('/en/try/', {'answer': answer, 'completion': 'completed', 'parent_report': 'easy', 'child': 'any-child', 'ticket': 'any-ticket', 'comment': 'PRIVATE-TEXT'})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, label)
            self.assertContains(response, 'Preview only')
            self.assertNotContains(response, 'PRIVATE-TEXT')
            self.assertNotContains(response, 'data-guided-activity')

    def test_stopped_preview_does_not_count_a_choice(self):
        response = self.client.post('/en/try/', {'answer': 'b', 'completion': 'stopped', 'parent_report': 'help'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stopped · no answer counted')
        self.assertNotContains(response, 'A different picture selected')

    def test_completed_preview_requires_valid_choices(self):
        for data in [
            {},
            {'completion': 'completed', 'parent_report': 'easy'},
            {'completion': 'completed', 'parent_report': 'easy', 'answer': 'injected'},
            {'completion': 'completed', 'parent_report': '<script>', 'answer': 'a'},
        ]:
            response = self.client.post('/en/try/', data)
            self.assertContains(response, 'role="alert"')
            self.assertNotContains(response, 'This is how a practice report is presented')

    @override_settings(DEMO_MODE=False)
    def test_public_preview_is_unavailable_in_real_mode(self):
        self.assertEqual(self.client.get('/en/try/').status_code, 404)
        self.assertEqual(self.client.post('/en/try/', {'answer': 'a', 'completion': 'completed', 'parent_report': 'easy'}).status_code, 404)
        self.assertNotContains(self.client.get('/en/'), 'href="/en/try/"')

    def test_preview_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        data = {'answer': 'a', 'completion': 'completed', 'parent_report': 'easy'}
        self.assertEqual(client.post('/en/try/', data).status_code, 403)
        client.get('/en/try/')
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post('/en/try/', {**data, 'csrfmiddlewaretoken': token}).status_code, 200)

    def test_home_links_to_the_interactive_preview(self):
        self.assertContains(self.client.get('/en/'), 'href="/en/try/"')
        self.assertEqual(self.client.put('/en/try/').status_code, 405)
