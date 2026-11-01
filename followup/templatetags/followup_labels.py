"""Display labels only: stored protocol/goal positions retain their original meaning."""
from django import template
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def target_position_label(value):
    labels = {
        'initial': _('Word initial'),
        'medial': _('Word medial'),
        'final': _('Word final'),
        'first_consonant': _('First consonant'),
    }
    return labels.get(value.strip().lower(), value) if isinstance(value, str) else value
