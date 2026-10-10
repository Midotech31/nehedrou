from django import template
from django.utils.safestring import mark_safe
register = template.Library()
PATHS = {
    'home': '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
    'profiles': '<circle cx="9" cy="8" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 3c2 1 3 3 3 6"/>',
    'library': '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4M5 5l3 3m8 8 3 3M5 19l3-3m8-8 3-3"/>',
    'security': '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>',
    'report': '<path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5"/>',
    'help': '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 4 3c-1 1-1 2-1 2M12 17h.01"/>',
    'arrow': '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    'check': '<path d="m4 12 5 5L20 6"/>',
    'logout': '<path d="M10 3H4v18h6M9 12h12m-5-5 5 5-5 5"/>',
}
@register.simple_tag
def icon(name):
    return mark_safe('<svg class="ui-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+PATHS.get(name,PATHS['report'])+'</svg>')
