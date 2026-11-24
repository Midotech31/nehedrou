"""Recovery-page copy from public transport configuration, never account state."""
from django.contrib.auth.views import PasswordResetDoneView, PasswordResetView

from .invitation_delivery import invitation_delivery_status


class RecoveryEmailContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['password_recovery_unavailable'] = invitation_delivery_status()['known_unavailable']
        return context


class PasswordRecoveryView(RecoveryEmailContextMixin, PasswordResetView):
    pass


class PasswordRecoveryDoneView(RecoveryEmailContextMixin, PasswordResetDoneView):
    pass
