from .auth_throttle import reserve_attempt, finish_attempt, limited_response
from django.utils.cache import patch_cache_control

class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        finish_attempt(request, response)
        recorder = request.path.endswith('/editorial/upload/') and request.user.is_authenticated
        response.headers['Permissions-Policy'] = ('microphone=(self)' if recorder else 'microphone=()') + ', camera=(), geolocation=()'
        referrer_policy = 'no-referrer' if response.headers.get('Referrer-Policy') == 'no-referrer' else 'same-origin'
        response.headers['Referrer-Policy'] = referrer_policy
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; media-src 'self' blob: https:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.user.is_authenticated or '/invite/' in request.path:
            patch_cache_control(response, private=True, no_store=True)
            # Preserve same-origin POST Origin for CSRF; never send paths cross-origin.
            response.headers['Referrer-Policy'] = referrer_policy
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        retry_after = reserve_attempt(request)
        if retry_after:
            return limited_response(retry_after)
        return None
