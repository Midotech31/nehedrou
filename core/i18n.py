from urllib.parse import parse_qsl, urlencode, urlsplit
from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import translate_url, reverse
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST


def _translate_route(destination, language):
    source = urlsplit(destination).path.strip('/').split('/')[0]
    with translation.override(source if source in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE):
        return translate_url(destination, language)


def _translate_login_continuation(destination, language, allowed_hosts, require_https):
    parsed = urlsplit(destination)
    with translation.override(language):
        if parsed.path != reverse('login'):
            return destination
    parameters = parse_qsl(parsed.query, keep_blank_values=True)
    localized = []
    for name, value in parameters:
        if name == 'next' and url_has_allowed_host_and_scheme(
            value, allowed_hosts=allowed_hosts, require_https=require_https,
        ):
            value = _translate_route(value, language)
        localized.append((name, value))
    if localized == parameters:
        return destination
    return parsed._replace(query=urlencode(localized)).geturl()


@require_POST
def switch_language(request):
    language = request.POST.get('language', '')
    if language not in dict(settings.LANGUAGES):
        language = settings.LANGUAGE_CODE
    destination = request.POST.get('next', '/')
    allowed_hosts = {request.get_host()}
    require_https = request.is_secure()
    if not url_has_allowed_host_and_scheme(destination, allowed_hosts=allowed_hosts, require_https=require_https):
        destination = '/'
    destination = _translate_route(destination, language)
    if not urlsplit(destination).path.startswith('/' + language + '/'):
        with translation.override(language):
            destination = reverse('home')
    else:
        destination = _translate_login_continuation(destination, language, allowed_hosts, require_https)
    response = HttpResponseRedirect(destination)
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=settings.LANGUAGE_COOKIE_AGE,
                        path=settings.LANGUAGE_COOKIE_PATH, domain=settings.LANGUAGE_COOKIE_DOMAIN,
                        secure=settings.LANGUAGE_COOKIE_SECURE, httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
                        samesite=settings.LANGUAGE_COOKIE_SAMESITE)
    return response
