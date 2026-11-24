"""Describe immutable review history, without deciding current qualification.

The ordering and exact-digest grouping mirror the publication gates. Matching a
digest does not verify the reviewer's current permissions or competence, media,
rights, independent reviewers, or an availability decision.
"""
from django.utils.translation import gettext_lazy as _


STATUS_LABELS = {
    'latest_for_content': _('Latest decision for this content fingerprint'),
    'superseded': _('Superseded decision for this content fingerprint'),
    'other_content': _('Decision for different content'),
}


def decision_history(reviews, current_digest):
    """Return presentation rows; never mutate decisions or create approvals.

    Latest means newest by ``created_at, pk`` for one discipline and the current
    content digest, exactly as in the activity, pack and protocol gates. A newer
    decision for another digest cannot supersede a decision for this content.
    """
    latest_kinds = set()
    rows = []
    for review in sorted(reviews, key=lambda row: (row.created_at, row.pk), reverse=True):
        if review.content_digest != current_digest:
            status = 'other_content'
        elif review.kind in latest_kinds:
            status = 'superseded'
        else:
            status = 'latest_for_content'
            latest_kinds.add(review.kind)
        rows.append({'review': review, 'status': status, 'label': STATUS_LABELS[status]})
    return rows
