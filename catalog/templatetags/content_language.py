"""Presentation language metadata never changes stored content or its approvals."""
import json
import re
from functools import lru_cache
from pathlib import Path
from django import template
from django.conf import settings
register = template.Library()

KNOWN_VARIETIES = {'fr-fr-pilot':'fr-FR', 'en-us-general-pilot':'en-US',
                   'ar-msa-pilot':'ar', 'ar-dz-pilot':'ar-DZ'}


def valid_language(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*',value) else 'und'


@register.filter
def spoken_language(value):
    """Use a frozen variety code or a live variety, independently of the menus."""
    code = value if isinstance(value,str) else getattr(value,'code','')
    if code in KNOWN_VARIETIES:
        return KNOWN_VARIETIES[code]
    if isinstance(value,str):
        if re.fullmatch(r'[a-z]{2,3}(?:-[A-Z]{2}|-[0-9]{3})?',value):
            return value
        return value.split('-')[0] if value.split('-')[0] in dict(settings.LANGUAGES) else 'und'
    return valid_language(getattr(value,'language',''))


@register.filter
def language_direction(value):
    return 'rtl' if str(value or '').split('-')[0].lower() in {'ar','arq','he','fa','ur'} else 'ltr'


@lru_cache(maxsize=1)
def source_declarations():
    # Match both the URL and the original scope so editorial changes never
    # inherit a translation intended for different content.
    path = Path(settings.BASE_DIR) / 'docs/source-language-declarations-20261030.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return {(entry['url'], entry['scope']): entry for entry in data['entries']}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def source_declaration(source):
    url, scope = source.get('url'), source.get('scope')
    if not isinstance(url, str) or not isinstance(scope, str):
        return {}
    return source_declarations().get((url, scope), {})


@register.filter
def source_scope_language(source):
    if not isinstance(source, dict):
        return 'und'
    if source.get('scope_language'):
        return valid_language(source['scope_language'])
    return source_declaration(source).get('scope_language', 'und')


@register.filter
def localized_source_scope(source, language):
    if not isinstance(source, dict):
        return {'text': '', 'language': 'und'}
    original_language = source_scope_language(source)
    declaration = source_declaration(source)
    if original_language == declaration.get('scope_language'):
        translated = declaration.get('translations', {}).get(language)
        if translated:
            return {'text': translated, 'language': language}
    return {'text': source.get('scope', ''), 'language': original_language}


@register.filter
def source_title_language(source):
    return valid_language(source.get('title_language','')) if isinstance(source,dict) else 'und'
