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


def public_example(language):
    # Read-only metadata; no ORM access, child data, history or persistence.
    pairs = {'fr': ('chat', 'rat'), 'en': ('coat', 'goat'), 'ar': ('دار', 'نار')}
    pair = pairs.get(language)
    return next((row for row in candidate_definitions() if row['variety_code'].startswith(language + '-')
                 and (row['word_a'], row['word_b']) == pair), None)
