from html.parser import HTMLParser

from django.conf import settings
from django.test import SimpleTestCase, Client
from django.utils import translation
from django.urls import reverse

class LanguageSelectorDOM(HTMLParser):
    """Read actual rendered selectors without simulating native activation."""
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current_form = None
        self.current_button = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'form':
            self.current_form = None
            if 'language' in attributes.get('class', '').split():
                self.current_form = {'attrs': attributes, 'inputs': [], 'buttons': [], 'groups': []}
                self.forms.append(self.current_form)
        if self.current_form is None:
            return
        if tag == 'input':
            self.current_form['inputs'].append(attributes)
        elif tag == 'button':
            self.current_button = {'attrs': attributes, 'text': ''}
            self.current_form['buttons'].append(self.current_button)
        if attributes.get('role') == 'group':
            self.current_form['groups'].append(attributes)

    def handle_endtag(self, tag):
        if tag == 'button':
            self.current_button = None
        elif tag == 'form':
            self.current_form = None

    def handle_data(self, data):
        if self.current_button is not None:
            self.current_button['text'] += data


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


    def test_language_selector_uses_native_submit_buttons_with_one_current_language(self):
        for language, _label in settings.LANGUAGES:
            with self.subTest(language=language):
                response = Client().get('/' + language + '/login/?next=/' + language + '/library/?q=chat')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.wsgi_request.LANGUAGE_CODE, language)
                dom = LanguageSelectorDOM(response.content.decode('utf-8'))
                self.assertEqual(len(dom.forms), 1)
                selector = dom.forms[0]
                self.assertEqual(selector['attrs'].get('method', '').lower(), 'post')
                self.assertEqual(selector['attrs'].get('action'), reverse('set_language'))
                hidden = {field.get('name'): field.get('value') for field in selector['inputs'] if field.get('type') == 'hidden'}
                self.assertTrue(hidden.get('csrfmiddlewaretoken'))
                self.assertEqual(hidden.get('next'), response.wsgi_request.get_full_path())
                self.assertEqual(len(selector['groups']), 1)
                self.assertTrue(selector['groups'][0].get('aria-label'))
                buttons = selector['buttons']
                self.assertEqual([button['attrs'].get('value') for button in buttons], [code for code, _label in settings.LANGUAGES])
                current = []
                for button in buttons:
                    attrs = button['attrs']
                    code = attrs['value']
                    self.assertEqual(attrs.get('type'), 'submit')
                    self.assertEqual(attrs.get('name'), 'language')
                    self.assertEqual(attrs.get('lang'), code)
                    self.assertEqual(button['text'].strip().casefold(), translation.get_language_info(code)['name_local'].casefold())
                    for forbidden in ('aria-pressed', 'aria-checked', 'aria-selected', 'role', 'disabled', 'hidden'):
                        self.assertNotIn(forbidden, attrs)
                    self.assertNotEqual(attrs.get('tabindex'), '-1')
                    if attrs.get('aria-current', 'false') != 'false':
                        self.assertEqual(attrs['aria-current'], 'true')
                        current.append(code)
                self.assertEqual(current, [language])
