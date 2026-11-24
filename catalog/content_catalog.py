"""Select new assignments without rewriting any historical content."""
import json
import uuid
from functools import lru_cache
from pathlib import Path
from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from .models import Activity


@lru_cache(maxsize=1)
def candidate_definitions():
    return json.loads((Path(settings.BASE_DIR) / 'docs/catalog-candidates.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def legacy_demo_series():
    rows = json.loads((Path(settings.BASE_DIR) / 'docs/catalog-candidates-v1.json').read_text(encoding='utf-8'))
    return [uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + row['series']) for row in rows] + [
        uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-demo:' + code)
        for code in ['fr-fr-pilot', 'en-us-general-pilot', 'ar-dz-pilot']
    ]


def current_catalog(queryset):
    # Known demonstration v1 records remain accessible through assigned history.
    # Only discovery/new assignment uses this selector. Non-demo rows are intact.
    newer = Activity.objects.filter(series=OuterRef('series'), version__gt=OuterRef('version'), state='published')
    return (queryset.exclude(Q(is_demo=True, series__in=legacy_demo_series(), version__lt=2))
            .annotate(_newer_published=Exists(newer)).filter(_newer_published=False))


def editorial_versions(queryset, *, include_history=False, content=''):
    """Choose latest authored versions independently of later state/type filters.

    A newer draft or withdrawal must not make an older filtered version appear
    current. Explicit history and exact-version links retain their normal scope.
    """
    if not include_history:
        newer = Activity.objects.filter(series=OuterRef('series'), version__gt=OuterRef('version'))
        queryset = queryset.annotate(_newer_editorial_version=Exists(newer)).filter(_newer_editorial_version=False)
    if content == 'candidate':
        queryset = queryset.filter(is_demo=False)
    elif content == 'demo':
        queryset = queryset.filter(is_demo=True)
    return queryset


@lru_cache(maxsize=1)
def public_arabic_definitions():
    # Read the shipped proposals only. No catalogue objects or clinical records.
    return json.loads((Path(settings.BASE_DIR) / 'docs/arabic-library-v1.json').read_text(encoding='utf-8'))['activities']


def public_example(language, variety_code=None):
    # Read-only metadata; no ORM access, child data, history or persistence.
    defaults = {'fr': 'fr-fr-pilot', 'en': 'en-us-general-pilot', 'ar': 'ar-dz-pilot'}
    variety_code = variety_code or defaults.get(language)
    pairs = {'fr-fr-pilot': ('chat', 'rat'), 'en-us-general-pilot': ('coat', 'goat'),
             'ar-dz-pilot': ('دار', 'نار'), 'ar-msa-pilot': ('قط', 'كلب')}
    pair = pairs.get(variety_code)
    if pair is None:
        return None
    rows = public_arabic_definitions() if variety_code == 'ar-msa-pilot' else candidate_definitions()
    return next((row for row in rows if row['variety_code'] == variety_code
                 and (row['word_a'], row['word_b']) == pair), None)
