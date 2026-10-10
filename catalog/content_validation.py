"""Validate editorial structure, never clinical correctness."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _

TEXT_FIELDS = {'objective', 'audience', 'review_notes'}
STEP_FIELDS = {'discover', 'listen', 'exchange', 'support', 'limits'}


def validate_content_guide(guide, references):
    if not isinstance(guide, dict) or any(code not in dict(settings.LANGUAGES) for code in guide):
        raise ValidationError(_('The structured guide must use supported language codes.'))
    for content in guide.values():
        if not isinstance(content, dict) or set(content) != TEXT_FIELDS | STEP_FIELDS:
            raise ValidationError(_('Each guide needs an objective, audience, three steps, support, limits and review notes.'))
        if any(not isinstance(content[key], str) or not content[key].strip() or len(content[key]) > 2000 for key in TEXT_FIELDS):
            raise ValidationError(_('Guide text must be non-empty and shorter than 2000 characters.'))
        for key in STEP_FIELDS:
            steps = content[key]
            if not isinstance(steps, list) or not 1 <= len(steps) <= 8 or any(not isinstance(text, str) or not text.strip() or len(text) > 2000 for text in steps):
                raise ValidationError(_('Each guide section needs one to eight non-empty text instructions.'))
    if not isinstance(references, list) or len(references) > 12:
        raise ValidationError(_('References must be a list of up to twelve sources.'))
    validate_url = URLValidator(schemes=['https'])
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {'title', 'url', 'scope'} or any(not isinstance(reference[key], str) or not reference[key].strip() for key in reference):
            raise ValidationError(_('Each source needs a title, an HTTPS URL and a statement of what it supports.'))
        validate_url(reference['url'])


def validate_item_definition(data, required=False):
    """Validate structure only: no IPA validity, indication or familiarity is inferred."""
    if not isinstance(data, dict):
        raise ValidationError(_('An item definition must be an object.'))
    if required and not str(data.get('meaning', '')).strip():
        raise ValidationError(_('The intended meaning is required.'))
    segments = data.get('segments', [])
    occurrences = data.get('target_occurrences', [])
    variants = data.get('accepted_variants', [])
    if not isinstance(segments, list) or any(not isinstance(s, str) or not s.strip() for s in segments) or (required and not segments):
        raise ValidationError(_('Segments must be an ordered list of phonemes.'))
    if not isinstance(occurrences, list) or (required and not occurrences):
        raise ValidationError(_('Identify at least one target occurrence.'))
    indices = set()
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValidationError(_('Each target occurrence needs an index, phoneme and position.'))
        index = occurrence.get('index')
        if type(index) is not int or index < 0 or index >= len(segments) or index in indices or occurrence.get('phoneme') != segments[index] or occurrence.get('position') not in ['initial','medial','final','other']:
            raise ValidationError(_('Target indices must identify unique matching phoneme segments and a position.'))
        indices.add(index)
    if not isinstance(variants, list) or any(not isinstance(v, dict) or not isinstance(v.get('ipa'),str) or not v['ipa'].strip() or not isinstance(v.get('reason'),str) or not v['reason'].strip() for v in variants):
        raise ValidationError(_('Admissible variants need an IPA form and an explicit reason.'))

def validate_item_metadata(metadata, required=False):
    if not isinstance(metadata, dict):
        raise ValidationError(_('Item metadata must be an object indexed by a and b.'))
    if not metadata and not required:
        return
    if set(metadata) != {'a','b'}:
        raise ValidationError(_('Document both words using the keys a and b.'))
    for data in metadata.values():
        validate_item_definition(data, required=required)
