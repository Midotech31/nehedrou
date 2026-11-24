"""Authenticated password rotation, with fresh validation under the account lock."""
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.db import transaction

from .auth_throttle import authentication_succeeded
from .models import User
from .services import audit


class AccountPasswordChangeView(PasswordChangeView):
    http_method_names = ['get', 'post', 'head', 'options']

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, '_locked_user'):
            kwargs['user'] = self._locked_user
        return kwargs

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        # The authenticated middleware user may predate another password change.
        # Construct and validate Django's form only after loading the locked row.
        try:
            self._locked_user = User.objects.select_for_update(no_key=True).get(
                pk=request.user.pk, is_active=True)
        except User.DoesNotExist:
            raise PermissionDenied from None
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        # Both the event and credential update roll back on either failure.
        # Audit first so a failed audit never rotates the current session key.
        audit(form.user, 'security.password_changed', form.user)
        response = super().form_valid(form)
        authentication_succeeded(self.request)
        return response
