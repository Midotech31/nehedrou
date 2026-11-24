from django import template
from catalog.reviewer_payload import reviewer_payload
register = template.Library()

@register.inclusion_tag('editorial/reviewer_payload.html', takes_context=True)
def activity_review_payload(context, activity, content_digest):
    return {'activity': activity, 'payload': reviewer_payload(activity, context.get('user')),
            'content_digest': content_digest}
