from django.urls import reverse
from django.utils.translation import gettext as _

def audio_context(asset, word='', variety='', reference_present=True):
    from .templatetags.content_language import spoken_language
    context = {'word': word, 'word_language': spoken_language(variety), 'reference_present': reference_present, 'asset': asset}
    if not asset:
        return context
    profile = asset.provenance.get('audio', {})
    if not isinstance(profile, dict): profile = {}
    source = profile.get('source', '')
    context['word_language'] = spoken_language(variety or profile.get('variety', ''))
    from .models import Variety
    variety_label = str(Variety(code=profile.get('variety', '')).display_label)
    context.update(url=reverse('editorial_media', args=[asset.pk]), seconds=asset.technical_metadata.get('seconds'),
                   word=word or profile.get('text', ''), audio_variety=variety_label,
                   audio_source={'human': _('Adult voice · requires human review'), 'synthetic': _('Synthetic voice · unreviewed demonstration'),
                                 'unspecified': _('Voice source not documented')}.get(source, _('Voice source not documented')))
    warnings = []
    signal = asset.technical_metadata.get('signal', {})
    if signal.get('silent'): warnings.append(_('This recording is silent. Record or upload a new file.'))
    elif signal.get('very_quiet'): warnings.append(_('The recording is very quiet. Check it before use.'))
    if signal.get('clipped_percent', 0) > .1: warnings.append(_('Possible saturation: record again further from the microphone.'))
    if variety and profile.get('variety') and variety != profile['variety']: warnings.append(_('The recording variety differs from this activity.'))
    if word and profile.get('text') and word != profile['text']: warnings.append(_('The recorded text differs from this word.'))
    context['audio_warnings'] = warnings
    return context


def media_choice_label(asset):
    from .models import Variety
    profile=asset.provenance.get('audio',{})
    if not isinstance(profile,dict): profile={}
    parts=[profile.get('text','') or asset.rights[:60]]
    label=str(Variety(code=profile.get('variety','')).display_label)
    if label: parts.append(label)
    parts.extend([asset.created_at.strftime('%Y-%m-%d'),str(asset.pk)[:8]])
    return ' · '.join(parts)
