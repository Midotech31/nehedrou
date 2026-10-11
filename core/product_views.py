from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from .access import visible_programs
from .planning import practice_dates, calendar_bytes

@login_required
@require_GET
def program_calendar(request, pk):
    program = get_object_or_404(visible_programs(request.user).select_related('child'), pk=pk)
    dates = practice_dates(program)
    if not dates:
        raise Http404
    response = HttpResponse(calendar_bytes(program, dates), content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="nehedrou-practice.ics"'
    response['Cache-Control'] = 'private, no-store'
    return response
