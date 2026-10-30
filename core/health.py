import time
from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def health(request):
    """Report database reachability without returning configuration or identities."""
    started = time.perf_counter()
    database_started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        database_ms = (time.perf_counter() - database_started) * 1000
        response = JsonResponse({'status': 'unavailable'}, status=503)
    else:
        database_ms = (time.perf_counter() - database_started) * 1000
        response = JsonResponse({'status': 'ok'})
    response['Cache-Control'] = 'no-store'
    response['Server-Timing'] = f'app;dur={(time.perf_counter() - started) * 1000:.3f}, db;dur={database_ms:.3f}'
    return response
