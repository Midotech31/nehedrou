from django import template
register = template.Library()


@register.filter
def guide_language(value, language):
    # Deliberately no language fallback for caregiver instructions.
    guide = value.get(language, {}) if isinstance(value, dict) else {}
    return dict(guide, language=language) if isinstance(guide, dict) and guide else {}


@register.simple_tag
def science_articles(language):
    from catalog.science_articles import ARTICLES
    return ARTICLES.get(language, [])
