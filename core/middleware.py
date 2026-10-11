import hashlib
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from .models import RateWindow
from django.http import HttpResponse
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext as _

class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.method == 'POST' and any(part in request.path for part in ['/login/', '/signup/', '/password-reset/', '/invite/', '/security/']):
            # REMOTE_ADDR is deliberately used rather than untrusted forwarding headers.
            key = hashlib.sha256(request.META.get('REMOTE_ADDR', '').encode()).hexdigest()
            with transaction.atomic():
                window, _created = RateWindow.objects.get_or_create(key=key)
                window = RateWindow.objects.select_for_update().get(pk=window.pk)
                if window.created_at < timezone.now() - timedelta(minutes=15):
                    window.created_at = timezone.now()
                    window.count = 0
                window.count += 1
                window.save(update_fields=['count', 'created_at'])
            if window.count > 15:
                return HttpResponse(_('Too many attempts. Try again in 15 minutes.'), status=429)
        response = self.get_response(request)
        recorder = request.path.endswith('/editorial/upload/') and request.user.is_authenticated
        response.headers['Permissions-Policy'] = ('microphone=(self)' if recorder else 'microphone=()') + ', camera=(), geolocation=()'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; media-src 'self' blob: https:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.user.is_authenticated or '/invite/' in request.path:
            patch_cache_control(response, private=True, no_store=True)
            # Preserve same-origin POST Origin for CSRF; never send paths cross-origin.
            response.headers['Referrer-Policy'] = 'same-origin'
        return response
