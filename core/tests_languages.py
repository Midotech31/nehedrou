from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from care.models import Child, FamilyLink
from core.access import CURRENT_NOTICE_VERSION
from core.models import Entitlement, Membership, NoticeAcknowledgement, Organization, User
from core.testing import practice_form_data

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
    def test_login_continuation_preserves_query_parameters_and_fragments(self):
        continuation = '/fr/library/?q=caf%C3%A9&variety=ar-dz-pilot#results'
        query = urlencode([('next', continuation), ('view', ''), ('view', 'full')])
        response = self.client.post('/i18n/setlang/', {
            'language': 'ar', 'next': f'/fr/login/?{query}#sign-in',
        })
        self.assertEqual(response.status_code, 302)
        redirect = urlsplit(response['Location'])
        self.assertEqual((redirect.path, redirect.fragment), ('/ar/login/', 'sign-in'))
        self.assertEqual(parse_qsl(redirect.query, keep_blank_values=True), [
            ('next', '/ar/library/?q=caf%C3%A9&variety=ar-dz-pilot#results'),
            ('view', ''), ('view', 'full'),
        ])

    def test_login_continuation_leaves_external_and_unknown_destinations_unchanged(self):
        cases = (
            ('https://outside.example/fr/library/', ''),
            ('/fr/unknown-page/', '/fr/unknown-page/'),
        )
        for destination, login_next in cases:
            with self.subTest(destination=destination):
                query = urlencode({'next': destination})
                altered = self.client.post('/i18n/setlang/', {
                    'language': 'en', 'next': f'/fr/login/?{query}',
                })
                self.assertEqual(altered['Location'], f'/en/login/?{query}')
                login = self.client.get(altered['Location'])
                self.assertEqual(login.context['next'], login_next)

    def test_language_switch_preserves_query_named_next_outside_login(self):
        query = urlencode({'next': '/fr/library/?q=original'})
        response = self.client.post('/i18n/setlang/', {
            'language': 'ar', 'next': f'/fr/library/?{query}',
        })
        self.assertEqual(response['Location'], f'/ar/library/?{query}')

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


@override_settings(
    DEMO_MODE=False, MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND='core.email_backends.DisabledEmailBackend', PUBLIC_ORIGIN='https://testserver',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class InvitationSignInLanguageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clinician = User.objects.create_user('language-clinician', 'clinician@example.test')
        cls.organization = Organization.objects.create(name='Fictional Language Practice')
        Membership.objects.create(user=cls.clinician, organization=cls.organization, role='clinician')
        Entitlement.objects.create(
            organization=cls.organization, expires_at=timezone.now() + timedelta(days=5),
            practitioner_quota=3, child_quota=3,
        )
        cls.child = Child.objects.create(
            organization=cls.organization, responsible=cls.clinician, code='Fictional child', age_years=5,
        )
        NoticeAcknowledgement.objects.create(
            user=cls.clinician, organization=cls.organization, version=CURRENT_NOTICE_VERSION, language='fr',
        )

    def test_existing_caregiver_keeps_selected_language_from_login_through_acceptance(self):
        self.client.force_login(self.clinician)
        for source, language in (('fr', 'ar'), ('ar', 'en'), ('en', 'fr')):
            with self.subTest(source=source, language=language):
                caregiver = User.objects.create_user(
                    f'language-caregiver-{source}', f'caregiver-{source}@example.test',
                    password='FixtureOnly-19!', instruction_language=source,
                )
                handoff = self.client.post(f'/{source}/children/{self.child.pk}/', {
                    'email': caregiver.email, 'delivery_method': 'manual', 'creation_id': str(uuid4()),
                })
                self.assertEqual(handoff.status_code, 200)
                invitation = urlsplit(handoff.context['manual_link']).path
                self.assertTrue(invitation.startswith(f'/{source}/invite/'))
                target_invitation = f'/{language}/' + invitation.split('/', 2)[2]

                recipient = Client()
                invite_form = recipient.get(invitation)
                sign_in = f'/{source}/login/?next={invitation}'
                self.assertContains(invite_form, f'href="{sign_in}"')
                login_form = recipient.get(sign_in)
                change = recipient.post('/i18n/setlang/', {
                    'language': language, 'next': login_form.wsgi_request.get_full_path(),
                })
                login = recipient.get(change['Location'])
                self.assertEqual(login.wsgi_request.LANGUAGE_CODE, language)
                self.assertEqual(login.context['next'], target_invitation)
                auth = recipient.post(change['Location'], {
                    'username': caregiver.username, 'password': 'FixtureOnly-19!', 'next': login.context['next'],
                })
                self.assertRedirects(auth, target_invitation, fetch_redirect_response=False)
                invite_form = recipient.get(auth['Location'])
                self.assertEqual(invite_form.wsgi_request.LANGUAGE_CODE, language)

                queued = recipient.post(auth['Location'])
                notice_path = f'/{language}/information/'
                self.assertRedirects(queued, notice_path, fetch_redirect_response=False)
                self.assertEqual(recipient.get(notice_path).wsgi_request.LANGUAGE_CODE, language)
                self.assertFalse(FamilyLink.objects.filter(child=self.child, user=caregiver).exists())
                accepted = recipient.post(notice_path, practice_form_data(recipient, notice_path))
                self.assertRedirects(accepted, f'/{language}/app/', fetch_redirect_response=False)
                self.assertTrue(FamilyLink.objects.filter(child=self.child, user=caregiver, active=True).exists())
                self.assertEqual(NoticeAcknowledgement.objects.get(
                    user=caregiver, organization=self.organization, version=CURRENT_NOTICE_VERSION,
                ).language, language)
                caregiver.refresh_from_db()
                self.assertEqual(caregiver.instruction_language, source)
