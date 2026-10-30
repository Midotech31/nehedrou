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
    variety = administration.snapshot.get('variety', '') if administration else definition.variety.code if definition else ''
    context = audio_context(asset,item.get('word',''),variety)
    if asset:
        context['url'] = reverse('followup:administration_media' if administration else 'followup:definition_media',args=[(administration or definition).pk,item['id'],'audio'])
    return context


@register.simple_tag
def editorial_image_srcset(reference):
    """Protected display derivatives only; ordinary historical paths stay intact."""
    from uuid import UUID
    from catalog.generated_pack import CONCEPTS, asset_id
    from catalog.integrity import request_value
    from catalog.models import GeneratedReviewPackImport
    from catalog.readiness import referenced_asset
    try:
        if not reference.startswith('editorial/asset-'):
            return ''
        key = UUID(reference[len('editorial/asset-'):])
    except (ValueError, AttributeError):
        return ''
    # These immutable IDs identify this requested pack only; this is no cache of
    # rights or file integrity. Ordinary historical assets need no extra query.
    if key not in {asset_id(concept, size) for concept in CONCEPTS for size in ['source', '512', '256']}:
        return ''
    asset = referenced_asset(reference, 'image')
    generation = asset.provenance.get('generation', {}) if asset and isinstance(asset.provenance, dict) else {}
    if not isinstance(generation, dict) or not generation.get('pack_id'):
        return ''
    receipt = request_value('generated_packs', generation['pack_id'],
        lambda: GeneratedReviewPackImport.objects.filter(pack_id=generation['pack_id']).first())
    variants = receipt.record.get('media', {}).get(generation.get('concept_id'), {}) if receipt else {}
    if not variants or str(asset.pk) not in [row['id'] for row in variants.values()]:
        return ''
    return ', '.join(reverse('editorial_media', args=[variants[size]['id']]) + ' ' + size + 'w' for size in ['256', '512'])
