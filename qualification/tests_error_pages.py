"""Production-mode 403/404 pages are branded, translated and reveal no exception text."""
from html.parser import HTMLParser

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.views.defaults import page_not_found, permission_denied

from catalog.models import EditorialGrant, Variety
from core.models import AuditEvent, User
from .models import LexicalPack


SETTINGS = dict(DEBUG=False, DEMO_MODE=True, MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['testserver'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},
              'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
LABELS = {
    'fr':{403:'Accès indisponible',404:'Page indisponible'},
    'en':{403:'Access unavailable',404:'Page unavailable'},
    'ar':{403:'الوصول غير متاح',404:'الصفحة غير متاحة'},
}


class ErrorPageDOM(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.document = {}
        self.main_ids = []
        self.links = []
        self.headings = []
        self.in_h1 = False
        self.in_title = False
        self.title = ''
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag=='html':
            self.document = attrs
        elif tag=='main':
            self.main_ids.append(attrs.get('id'))
        elif tag=='a':
            self.links.append(attrs.get('href'))
        elif tag=='title':
            self.in_title = True
        elif tag=='h1':
            self.in_h1 = True
            self.headings.append('')

    def handle_endtag(self, tag):
        if tag=='title':
            self.in_title = False
        if tag=='h1':
            self.in_h1 = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_h1:
            self.headings[-1] += data


def assert_error_page(case, response, language, status, *, authenticated):
    case.assertEqual(response.status_code,status)
    text = response.content.decode('utf-8')
    dom = ErrorPageDOM(text)
    case.assertEqual(dom.document.get('lang'),language)
    case.assertEqual(dom.document.get('dir'),'rtl' if language=='ar' else 'ltr')
    case.assertEqual(dom.main_ids,['main'])
    case.assertEqual(dom.title.strip(),LABELS[language][status]+' · Nehedrou')
    case.assertEqual([heading.strip() for heading in dom.headings],[LABELS[language][status]])
    case.assertIn('/'+language+'/',dom.links)
    if authenticated:
        case.assertIn('/'+language+'/app/',dom.links)
    case.assertIn('nehedrou-child-profile',text)
    case.assertIn('Designed by Benabdeloued Mohamed Alias Pitou',text)
    if language=='ar':
        case.assertIn('Tajawal-Medium.ttf',text)


@override_settings(**SETTINGS)
class PublicErrorPageTests(SimpleTestCase):
    def test_unknown_routes_render_localised_404_without_database_access(self):
        for language in ('fr','en','ar'):
            with self.subTest(language=language):
                response = self.client.get('/'+language+'/unknown-recipe-route/',secure=True,HTTP_ACCEPT_LANGUAGE='en')
                assert_error_page(self,response,language,404,authenticated=False)

    def test_default_handlers_never_render_exception_messages(self):
        sentinel = 'PRIVATE_OBJECT_EXCEPTION_SENTINEL'
        for language in ('fr','en','ar'):
            with translation.override(language):
                request = RequestFactory().get('/'+language+'/generic-error-fixture/',secure=True)
                request.user = AnonymousUser()
                for handler,error,status in [(page_not_found,Http404(sentinel),404),
                                             (permission_denied,PermissionDenied(sentinel),403)]:
                    with self.subTest(language=language,status=status):
                        response = handler(request,error)
                        assert_error_page(self,response,language,status,authenticated=False)
                        self.assertNotIn(sentinel,response.content.decode('utf-8'))


@override_settings(**SETTINGS)
class RestrictedErrorPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(code='fr-error-fixture',language='fr',label='Fictional error-page variety')
        cls.reviewer = User.objects.create_user(username='error-page-reviewer',email='error-page-reviewer@example.test')
        EditorialGrant.objects.create(user=cls.reviewer,variety=cls.variety,clinical_review=True)
        cls.family = User.objects.create_user(username='error-page-family',email='error-page-family@example.test')

    def test_review_only_pack_creation_retains_403_with_localised_recovery_links(self):
        self.client.force_login(self.reviewer)
        original = (User.objects.count(),EditorialGrant.objects.count(),LexicalPack.objects.count(),AuditEvent.objects.count())
        for language in ('fr','en','ar'):
            with translation.override(language):
                path = reverse('qualification:pack_new')
            with self.subTest(language=language),translation.override('en'):
                response = self.client.get(path,secure=True,HTTP_ACCEPT_LANGUAGE='en')
                assert_error_page(self,response,language,403,authenticated=True)
                self.assertEqual((User.objects.count(),EditorialGrant.objects.count(),LexicalPack.objects.count(),AuditEvent.objects.count()),original)

    def test_account_without_editorial_access_gets_localised_403_from_each_url_prefix(self):
        self.client.force_login(self.family)
        original = (User.objects.count(),EditorialGrant.objects.count(),LexicalPack.objects.count(),AuditEvent.objects.count())
        for language in ('fr','en','ar'):
            with translation.override(language):
                path = reverse('qualification:index')
            with self.subTest(language=language),translation.override('en'):
                response = self.client.get(path,secure=True,HTTP_ACCEPT_LANGUAGE='en')
                assert_error_page(self,response,language,403,authenticated=True)
                self.assertEqual((User.objects.count(),EditorialGrant.objects.count(),LexicalPack.objects.count(),AuditEvent.objects.count()),original)
