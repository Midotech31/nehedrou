from django.test import SimpleTestCase, Client
from django.utils import translation
from django.urls import reverse

class LanguageSwitchTests(SimpleTestCase):
    def test_all_pairs_without_cookie_or_referer(self):
        for source in ['fr','en','ar']:
            for target in ['fr','en','ar']:
                c=Client()
                response=c.post('/i18n/setlang/', {'language':target, 'next':f'/{source}/library/?q=chat'})
                self.assertEqual(response.status_code,302)
                self.assertEqual(response.headers['Location'],f'/{target}/library/?q=chat')
                self.assertEqual(response.cookies['django_language'].value,target)
    def test_external_destination_is_rejected(self):
        r=self.client.post('/i18n/setlang/',{'language':'ar','next':'https://evil.example/steal'})
        self.assertEqual(r.headers['Location'],'/ar/')
    def test_navigation_switch_requires_post(self):
        self.assertEqual(self.client.get('/i18n/setlang/').status_code,405)

    def test_translations_exist_for_workspace_labels(self):
        labels = ['Account security', 'Content language', 'Practice rhythm', 'Search by pseudonym', 'Explore activity']
        for language in ['fr', 'ar']:
            with translation.override(language):
                for label in labels:
                    self.assertNotEqual(translation.gettext(label), label, (language,label))
