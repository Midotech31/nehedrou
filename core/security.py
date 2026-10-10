import hashlib
import io
import secrets
from base64 import b32encode
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_otp import login as otp_login, verify_token
from django_otp.plugins.otp_totp.models import TOTPDevice
from .models import RecoveryCode, Membership
from .services import audit

class MFAMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.user.is_authenticated:
            has_device = TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
            from catalog.models import EditorialGrant
            privileged = (request.user.is_staff or request.user.is_superuser
                          or Membership.objects.filter(user=request.user, active=True).exists()
                          or EditorialGrant.objects.filter(user=request.user).exists()
                          or request.user.has_perm('core.manage_entitlements'))
            if (has_device or (settings.MFA_REQUIRED and privileged)) and not request.user.is_verified():
                allowed = ['/security/', '/logout/', '/static/', '/i18n/']
                if not any(part in request.path for part in allowed):
                    return redirect('mfa_verify' if has_device else 'mfa_setup')
        return self.get_response(request)

class SetupForm(forms.Form):
    password = forms.CharField(label=_('Current password'), widget=forms.PasswordInput)
    token = forms.CharField(label=_('Authenticator code'), min_length=6, max_length=8)

class TokenForm(forms.Form):
    token = forms.CharField(label=_('Authenticator code or recovery code'), max_length=64)

@login_required
def setup(request):
    confirmed = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    if confirmed:
        return redirect('mfa_verify') if not request.user.is_verified() else render(request, 'notice.html', {'title': _('Two-factor authentication'), 'body': _('Protection is active. Recovery codes can be regenerated after verification.')})
    device, _created = TOTPDevice.objects.get_or_create(user=request.user, name='primary', confirmed=False)
    form = SetupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if not request.user.check_password(form.cleaned_data['password']):
            form.add_error('password', _('The password is incorrect.'))
        else:
            with transaction.atomic():
                device = TOTPDevice.objects.select_for_update().get(pk=device.pk)
                valid = device.verify_token(form.cleaned_data['token'])
                if valid:
                    device.confirmed = True
                    device.save()
                    RecoveryCode.objects.filter(user=request.user).delete()
                    codes = [secrets.token_hex(12) for _ in range(8)]
                    for code in codes:
                        RecoveryCode.objects.create(user=request.user, digest=hashlib.sha256(code.encode()).hexdigest())
                    otp_login(request, device)
                    audit(request.user, 'security.mfa_enabled', request.user)
            if valid:
                return render(request, 'security_codes.html', {'codes': codes})
            form.add_error('token', _('Invalid or already used code.'))
    return render(request, 'security_setup.html', {'form': form, 'secret': b32encode(device.bin_key).decode()})

@login_required
def qr(request):
    device = TOTPDevice.objects.filter(user=request.user, confirmed=False, name='primary').first()
    if not device:
        return HttpResponse(status=404)
    import segno
    output = io.BytesIO()
    segno.make(device.config_url).save(output, kind='svg', scale=5, xmldecl=False)
    response = HttpResponse(output.getvalue(), content_type='image/svg+xml')
    response['Cache-Control'] = 'no-store, private'
    return response

@login_required
def verify(request):
    device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    if not device:
        return redirect('mfa_setup')
    form = TokenForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        token = form.cleaned_data['token'].strip()
        verified = verify_token(request.user, device.persistent_id, token) if token.isdigit() else None
        if not verified:
            with transaction.atomic():
                recovery = RecoveryCode.objects.select_for_update().filter(user=request.user, digest=hashlib.sha256(token.encode()).hexdigest()).first()
                if recovery:
                    recovery.delete()
                    verified = device
                    audit(request.user, 'security.recovery_used', request.user)
        if verified:
            otp_login(request, verified)
            return redirect('dashboard')
        form.add_error('token', _('Invalid or already used code.'))
    return render(request, 'form.html', {'title': _('Verify your identity'), 'form': form, 'submit': _('Verify')})

@login_required
def recovery_codes(request):
    if not request.user.is_verified():
        return redirect('mfa_verify')
    form = SetupForm(request.POST or None)
    form.fields.pop('token')
    if request.method == 'POST' and form.is_valid():
        if not request.user.check_password(form.cleaned_data['password']):
            form.add_error('password', _('The password is incorrect.'))
        else:
            with transaction.atomic():
                from .models import User
                User.objects.select_for_update().get(pk=request.user.pk)
                RecoveryCode.objects.filter(user=request.user).delete()
                codes = [secrets.token_hex(12) for _ in range(8)]
                for code in codes:
                    RecoveryCode.objects.create(user=request.user, digest=hashlib.sha256(code.encode()).hexdigest())
                audit(request.user, 'security.recovery_regenerated', request.user)
            return render(request, 'security_codes.html', {'codes': codes})
    return render(request, 'form.html', {'title': _('Regenerate recovery codes'), 'form': form, 'submit': _('Regenerate')})
