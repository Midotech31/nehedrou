from urllib.parse import urlsplit
from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import translate_url, reverse
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

@require_POST
def switch_language(request):
    language = request.POST.get('language', '')
    if language not in dict(settings.LANGUAGES):
        language = settings.LANGUAGE_CODE
    destination = request.POST.get('next', '/')
    if not url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        destination = '/'
    source = urlsplit(destination).path.strip('/').split('/')[0]
    with translation.override(source if source in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE):
        destination = translate_url(destination, language)
    if not urlsplit(destination).path.startswith('/' + language + '/'):
        with translation.override(language):
            destination = reverse('home')
    response = HttpResponseRedirect(destination)
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=settings.LANGUAGE_COOKIE_AGE,
                        path=settings.LANGUAGE_COOKIE_PATH, domain=settings.LANGUAGE_COOKIE_DOMAIN,
                        secure=settings.LANGUAGE_COOKIE_SECURE, httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
                        samesite=settings.LANGUAGE_COOKIE_SAMESITE)
    return response
