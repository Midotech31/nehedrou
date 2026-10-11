"""Protect probe words from structured family-facing practice material."""
from followup.services import reserved_words_for
from followup.validation import reserve_word_key


def reserved_activity_ids(child, activities):
    by_variety = {}
    blocked = set()
    for activity in activities:
        if activity.variety_id not in by_variety:
            by_variety[activity.variety_id] = {reserve_word_key(word, activity.variety)
                for word in reserved_words_for(child, activity.variety)}
        reserved = by_variety[activity.variety_id]
        if any(reserve_word_key(word, activity.variety) in reserved for word in (activity.word_a, activity.word_b)):
            blocked.add(activity.pk)
    return blocked


def activity_is_reserved(child, activity):
    return activity.pk in reserved_activity_ids(child, [activity])


def family_catalog_exclusions(actor, activities):
    from .access import professional_children, visible_children
    rows = list(activities)
    family_only_children = visible_children(actor).exclude(pk__in=professional_children(actor))
    return set().union(*(reserved_activity_ids(child, rows) for child in family_only_children))
