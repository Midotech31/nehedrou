"""Known technical and binding failures; human phonetic judgement is separate."""
from django.utils.translation import gettext as _

def audio_binding_errors(asset, word, variety):
    reasons=[]
    signal=asset.technical_metadata.get('signal',{})
    if signal.get('silent'): reasons.append(_('A silent recording cannot be used as a speech model.'))
    profile=asset.provenance.get('audio',{})
    if isinstance(profile,dict) and profile:
        if profile.get('variety') != getattr(variety,'code','') or profile.get('text') != word:
            reasons.append(_('The recording must match the exact word and spoken variety of the activity.'))
    return reasons
