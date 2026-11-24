"""Request-local presentation of the authoritative Activity.usable gate.

Callers retain their existing current-version, role and reserve-word filters.
Only pass the visible page or the submitted choices: this helper deliberately
does not discover or scan the rest of the catalogue.
"""
from .integrity import prepare_activities, request_value


def prepare_availability(activities, *, include_audio=False):
    rows = prepare_activities(list(activities))
    for activity in rows:
        activity.presentation_available = request_value(
            'presentation_availability', activity.pk, lambda: bool(activity.usable))
        if include_audio:
            # Real usability already requires both exact qualified audio assets.
            # Demo playback is a separate, non-clinical file-presence check.
            activity.presentation_audio_available = bool(activity.presentation_available and (
                not activity.is_demo or all(activity.audio_available(reference)
                    for reference in (activity.audio_a, activity.audio_b))))
    return rows
