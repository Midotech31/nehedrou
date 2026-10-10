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
