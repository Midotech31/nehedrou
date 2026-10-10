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
