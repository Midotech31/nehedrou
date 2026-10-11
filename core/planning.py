"""Clinician-selected dates and descriptive participation; no automatic prescription."""
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

def validate_plan(start, end, days, minutes):
    errors = {}
    if not isinstance(days, list) or any(type(day) is not int or day not in range(7) for day in days) or len(days) != len(set(days)):
        errors['practice_days'] = _('Choose each practice day only once.')
    if minutes is not None and (type(minutes) is not int or not 1 <= minutes <= 120):
        errors['practice_minutes'] = _('Enter planned minutes between 1 and 120.')
    if start or end or days or minutes is not None:
        if not start:
            errors['practice_start'] = _('Choose a start date for the practice plan.')
        if not end:
            errors['practice_end'] = _('Choose an end date for the practice plan.')
        if not days:
            errors['practice_days'] = _('Choose at least one agreed day.')
        if start and end and end < start:
            errors['practice_end'] = _('The plan must end on or after its start date.')
        elif start and end and 'practice_days' not in errors:
            if not any((start.weekday() + i) % 7 in days for i in range(min((end-start).days+1, 7))):
                errors['practice_days'] = _('No agreed day occurs within these dates.')
    if errors:
        raise ValidationError(errors)

def practice_dates(program, *, today=None, horizon=28):
    today = today or timezone.localdate()
    if program.state != 'active' or not program.child.active or not program.practice_start or not program.practice_end or not program.practice_days:
        return []
    return [today + timedelta(days=i) for i in range(horizon)
            if program.practice_start <= today + timedelta(days=i) <= program.practice_end
            and (today + timedelta(days=i)).weekday() in program.practice_days]

def decorate_plan(program, *, today=None):
    today = today or timezone.localdate()
    dates = practice_dates(program, today=today)
    program.has_practice_plan = bool(program.practice_start and program.practice_end and program.practice_days)
    program.next_practice_dates = dates[:7]
    program.practice_today = today in dates
    program.plan_expired = bool(program.practice_end and program.practice_end < today)
    return program

def activity_overview(items, sessions):
    values = {row['item_id']: row for row in sessions.order_by().values('item_id').annotate(
        reports=Count('pk'), completed=Count('pk', filter=Q(completion='completed')),
        stopped=Count('pk', filter=Q(completion='stopped')),
        help=Count('pk', filter=~Q(parent_report='easy')),
        answered=Count('pk', filter=Q(correct__isnull=False)),
        correct=Count('pk', filter=Q(correct=True)), last=Max('created_at'))}
    return [dict(item=item, **values.get(item.pk, dict(reports=0, completed=0, stopped=0, help=0, answered=0, correct=0, last=None))) for item in items]

def calendar_bytes(program, dates):
    # Generic dates only: no pseudonym, program name, notes, identifier, URL or health data.
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Nehedrou//Practice dates//EN', 'CALSCALE:GREGORIAN']
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    for day in dates:
        lines += ['BEGIN:VEVENT', f'UID:practice-{day:%Y%m%d}@nehedrou.example', f'DTSTAMP:{stamp}',
                  f'DTSTART;VALUE=DATE:{day:%Y%m%d}', f'DTEND;VALUE=DATE:{day+timedelta(days=1):%Y%m%d}',
                  'SUMMARY:Nehedrou practice', 'TRANSP:TRANSPARENT', 'END:VEVENT']
    return ('\r\n'.join(lines + ['END:VCALENDAR']) + '\r\n').encode('ascii')
