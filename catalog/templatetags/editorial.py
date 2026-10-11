from django import template
from django.templatetags.static import static
from django.urls import reverse

register = template.Library()

@register.simple_tag
def editorial_image(reference):
    prefix = 'editorial/asset-'
    if reference.startswith(prefix):
        return reverse('editorial_media', args=[reference[len(prefix):]])
    return static(reference)


def audio_context(asset, word='', variety='', reference_present=True):
    from catalog.audio_presentation import audio_context as context
    return context(asset, word, variety, reference_present)

@register.inclusion_tag('audio_player.html')
def activity_audio(activity, side):
    from catalog.readiness import referenced_asset
    reference = getattr(activity, 'audio_' + side, '') if side in ['a', 'b'] else ''
    asset = referenced_asset(reference, 'audio') if reference else None
    return audio_context(asset, getattr(activity, 'word_' + side, '') if side in ['a', 'b'] else '', activity.variety.code, bool(reference) or not activity.device_voice_allowed)

@register.inclusion_tag('audio_player.html')
def media_audio(asset):
    return audio_context(asset)


@register.inclusion_tag('audio_player.html')
def probe_audio(item, definition=None, administration=None):
    from catalog.models import MediaAsset
    asset = MediaAsset.objects.filter(pk=item.get('audio_asset'),kind='audio').first()
    context = audio_context(asset,item.get('word',''))
    if asset:
        context['url'] = reverse('followup:administration_media' if administration else 'followup:definition_media',args=[(administration or definition).pk,item['id'],'audio'])
    return context
