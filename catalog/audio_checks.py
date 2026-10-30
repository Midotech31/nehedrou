"""Known technical and binding failures; human phonetic judgement is separate."""
from django.utils.translation import gettext as _


def valid_audio_profile(profile):
    return bool(isinstance(profile, dict)
        and profile.get('source') in ['human', 'synthetic']
        and isinstance(profile.get('text'), str) and profile['text'].strip()
        and isinstance(profile.get('variety'), str) and profile['variety'].strip())


def audio_binding_errors(asset, word, variety):
    reasons = []
    signal = asset.technical_metadata.get('signal', {})
    if signal.get('silent'):
        reasons.append(_('A silent recording cannot be used as a speech model.'))
    profile = asset.provenance.get('audio') if isinstance(asset.provenance, dict) else None
    if not valid_audio_profile(profile):
        reasons.append(_('Real-use audio requires the exact spoken text, spoken variety and a documented human or synthetic source.'))
    elif profile['variety'] != getattr(variety, 'code', '') or profile['text'] != word:
        reasons.append(_('The recording must match the exact word and spoken variety of the activity.'))
    return reasons
