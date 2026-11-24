"""Recovery-page copy from public transport configuration, never account state."""
from django.contrib.auth.views import PasswordResetDoneView, PasswordResetView
from django.http import HttpResponseRedirect

from .invitation_delivery import invitation_delivery_status


class RecoveryEmailContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['password_recovery_unavailable'] = invitation_delivery_status()['known_unavailable']
        return context


class PasswordRecoveryView(RecoveryEmailContextMixin, PasswordResetView):
    def form_valid(self, form):
        if invitation_delivery_status()['known_unavailable']:
            # Keep the same response for every address without looking up accounts.
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class PasswordRecoveryDoneView(RecoveryEmailContextMixin, PasswordResetDoneView):
    pass
