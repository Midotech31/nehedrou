import uuid
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import EditorialAccessInvitation, Variety

class EditorialAccessInvitationForm(forms.Form):
    creation_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    delivery_method = forms.ChoiceField(
        choices=[('email', _('Email')), ('manual', _('Personal handoff link'))],
        required=False, initial='email', label=_('Delivery method'))
    email = forms.EmailField(label=_('Reviewer or editor email'))
    variety = forms.ModelChoiceField(queryset=Variety.objects.none(), label=_('Spoken variety'))
    capability = forms.ChoiceField(choices=EditorialAccessInvitation.CAPABILITIES, label=_('Limited editorial role'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variety'].queryset = Variety.objects.order_by('code')
        if not self.is_bound:
            self.initial['creation_id'] = uuid.uuid4()

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean(self):
        data = super().clean()
        data['delivery_method'] = data.get('delivery_method') or 'email'
        if data['delivery_method'] == 'manual' and not data.get('creation_id'):
            self.add_error('creation_id', _('Open a new form to create a personal handoff link.'))
        return data
