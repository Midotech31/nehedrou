from django.utils.translation import gettext as _
"""Structural safeguards for human observation; no phonetic certification."""
import unicodedata
import re
from django.core.exceptions import ValidationError

CODES = ('TARGET_ACCEPTABLE', 'VARIANT_ACCEPTABLE', 'TARGET_INCORRECT', 'NOT_SCORABLE', 'NOT_PRESENTED')
ELICITATIONS = ('naming', 'semantic_cue', 'lexical_choice', 'imitation')
RIGHTS_STATUSES = ('unknown', 'original_documented', 'open_commercial_compatible', 'permission_required', 'excluded')
CONDITION_KEYS = {'place', 'task', 'fatigue', 'noise', 'interruption', 'instructions', 'audio_equipment', 'attempt_rule'}


TARGET_POSITIONS = ('initial', 'medial', 'final')


def validate_target_scope(scope):
    # Empty remains explicitly undocumented; migrations never infer a context.
    if scope == {}:
        return
    if not isinstance(scope, dict) or set(scope) != {'position', 'context'} or scope.get('position') not in TARGET_POSITIONS:
        raise ValidationError(_('Document a structured target position and context.'))
    if not isinstance(scope.get('context'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', scope['context']):
        raise ValidationError(_('Use an explicit stable context identifier, such as isolated_word.'))


def target_match_errors(goal, definition):
    errors = []
    if goal.variety_id != definition.variety_id:
        errors.append(_('The protocol and goal must use the same spoken variety.'))
    if phoneme_key(goal.target_phoneme) != phoneme_key(definition.target_phoneme):
        errors.append(_('The protocol target must match the clinical goal target.'))
    if not goal.target_scope or not definition.target_scope:
        errors.append(_('Position and context are undocumented; use a named, justified separate observation.'))
    elif goal.target_scope != definition.target_scope:
        errors.append(_('The protocol position and context must match the clinical goal.'))
    return errors


def validate_observation_target(goal, definition, scope='goal', label='', reason=''):
    if scope not in ['goal', 'alternate_context']:
        raise ValidationError(_('Choose a goal observation or a separate context observation.'))
    # An alternate context never bypasses phoneme or variety identity.
    if goal.variety_id != definition.variety_id or phoneme_key(goal.target_phoneme) != phoneme_key(definition.target_phoneme):
        raise ValidationError(_('The protocol target and spoken variety must match the clinical goal.'))
    if scope == 'alternate_context':
        if not isinstance(label, str) or not label.strip() or len(label) > 160 or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValidationError(_('Name and justify this separate context observation.'))
    else:
        errors = target_match_errors(goal, definition)
        if errors:
            raise ValidationError(errors)
        if label or reason:
            raise ValidationError(_('Separate-context details require the separate observation mode.'))


def word_key(word):
    return ' '.join(unicodedata.normalize('NFC', word).casefold().split())


def reserve_word_key(word, variety):
    """Conservative spelling comparison, never a clinical lexeme/IPA rewrite.

    Arabic marks can distinguish meanings. Treating their omission as a match
    prevents an uncertain spelling from establishing non-exposure or bypassing
    a family reserve; it does not certify that two productions are equivalent.
    """
    key = word_key(word)
    if variety.language == 'ar':
        key = re.sub(r'[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]', '', key)
    return key


def phoneme_key(value):
    """Normalize enclosing IPA delimiters, never split IPA into characters."""
    return unicodedata.normalize('NFC', value.strip().strip('/[]').strip())


def validate_variants(variants):
    if not isinstance(variants, list) or len(variants) > 30:
        raise ValidationError(_('Accepted variants must be a bounded list.'))
    seen = set()
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) - {'id', 'label', 'ipa'} or not all(isinstance(variant.get(k), str) and variant[k].strip() for k in ['id', 'label']):
            raise ValidationError(_('Each variant needs an explicit id and label.'))
        if variant['id'] in seen or any(len(str(v)) > 200 for v in variant.values()):
            raise ValidationError(_('Variant identifiers must be unique and text bounded.'))
        seen.add(variant['id'])


def validate_items(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 60:
        raise ValidationError(_('A protocol needs one to sixty explicit items.'))
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError(_('Each protocol item must be an object.'))
        for key in ['id', 'word', 'ipa', 'target_definition']:
            if not isinstance(item.get(key), str) or not item[key].strip() or len(item[key]) > 500:
                raise ValidationError(_('Each item needs an id, word, proposed IPA and target definition.'))
        if item['id'] in ids:
            raise ValidationError(_('Protocol item identifiers must be unique.'))
        ids.add(item['id'])
        index = item.get('target_occurrence_index')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 99:
            raise ValidationError(_('Identify the target occurrence explicitly.'))
        meaning = item.get('meaning', '')
        segments = item.get('segments', [])
        occurrences = item.get('target_occurrences', [])
        if not isinstance(meaning, str) or len(meaning) > 1000:
            raise ValidationError(_('Item meaning must be bounded text.'))
        if not isinstance(segments, list) or len(segments) > 100 or any(not isinstance(s, str) or not s.strip() or len(s) > 40 for s in segments):
            raise ValidationError(_('Phonemic segments must be an explicit bounded list, not IPA characters.'))
        if segments and index >= len(segments):
            raise ValidationError(_('The target index must identify a documented phonemic segment.'))
        if not isinstance(occurrences, list) or len(occurrences) > 100:
            raise ValidationError(_('Documented occurrences must be a bounded list.'))
        occurrence_indices = set()
        for occurrence in occurrences:
            if not isinstance(occurrence, dict) or set(occurrence) - {'index', 'phoneme', 'id', 'position', 'context'}:
                raise ValidationError(_('Each documented occurrence needs a segment index and phoneme.'))
            occurrence_index = occurrence.get('index')
            phoneme = occurrence.get('phoneme')
            if isinstance(occurrence_index, bool) or not isinstance(occurrence_index, int) or not 0 <= occurrence_index < len(segments) or occurrence_index in occurrence_indices:
                raise ValidationError(_('Documented occurrence indices must identify distinct phonemic segments.'))
            if not isinstance(phoneme, str) or not phoneme.strip() or phoneme_key(phoneme) != phoneme_key(segments[occurrence_index]):
                raise ValidationError(_('The occurrence phoneme must match its documented segment.'))
            if any(not isinstance(value, str) or len(value) > 500 for key, value in occurrence.items() if key != 'index'):
                raise ValidationError(_('Documented occurrence descriptions must be bounded text.'))
            occurrence_indices.add(occurrence_index)
        if item.get('exposure_plan') not in ['trained', 'reserved', 'uncertain']:
            raise ValidationError(_('Distinguish trained, reserved and uncertain item plans.'))
        validate_variants(item.get('accepted_variants', []))
        attempt = item.get('selected_attempt', 1)
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 20:
            raise ValidationError(_('The retained attempt must be defined before administration.'))


def validate_conditions(conditions):
    if not isinstance(conditions, dict) or set(conditions) - CONDITION_KEYS:
        raise ValidationError(_('Use the documented observation conditions.'))
    if any(not isinstance(v, str) or len(v) > 2000 for v in conditions.values()):
        raise ValidationError(_('Conditions must be bounded text.'))
    if not conditions.get('attempt_rule', '').strip():
        raise ValidationError(_('Define the retained-attempt rule before observing.'))


def validate_rating(data, item, goal_variants):
    if data.get('code') not in CODES or data.get('elicitation') not in ELICITATIONS:
        raise ValidationError(_('Select a supported human rating and actual elicitation.'))
    code = data['code']
    for key in ['attempted_expected_word', 'target_identifiable']:
        if not isinstance(data.get(key), bool):
            raise ValidationError(_('Document whether the expected word and target were audible.'))
    attempt = data.get('attempt_index', 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        raise ValidationError(_('Identify the predetermined retained attempt.'))
    if code != 'NOT_PRESENTED' and attempt != item.get('selected_attempt', 1):
        raise ValidationError(_('Keep the attempt predetermined by this protocol version.'))
    if code in ['TARGET_ACCEPTABLE', 'VARIANT_ACCEPTABLE', 'TARGET_INCORRECT'] and not (data['attempted_expected_word'] and data['target_identifiable']):
        raise ValidationError(_('A scorable response requires an audible expected word and an identifiable target.'))
    variants = {v['id'] for v in item.get('accepted_variants', []) + goal_variants}
    if code == 'VARIANT_ACCEPTABLE' and data.get('variant_id') not in variants:
        raise ValidationError(_('Name a variant documented before the observation.'))
    if code != 'VARIANT_ACCEPTABLE' and data.get('variant_id'):
        raise ValidationError(_('An accepted variant belongs only to the variant rating.'))
    if code == 'NOT_SCORABLE' and not data.get('exclusion_reason', '').strip():
        raise ValidationError(_('Explain an unscorable response, including refusal or interruption.'))
    if code == 'TARGET_INCORRECT' and data.get('error_type') not in ['substitution', 'omission', 'distortion', 'other']:
        raise ValidationError(_('An audible error needs its error type; refusal is unscorable.'))
    if code != 'TARGET_INCORRECT' and data.get('error_type'):
        raise ValidationError(_('Error type is reserved for scorable target errors.'))
    if code == 'NOT_PRESENTED' and (data['attempted_expected_word'] or data['target_identifiable'] or data.get('transcription')):
        raise ValidationError(_('An unpresented item cannot contain an observed production.'))
    for key in ['assistance', 'transcription', 'variant_id', 'exclusion_reason', 'error_type']:
        if not isinstance(data.get(key, ''), str) or len(data.get(key, '')) > 2000:
            raise ValidationError(_('Rating notes must be bounded text.'))
