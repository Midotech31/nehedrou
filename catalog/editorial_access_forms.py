from django import forms
from django.utils.translation import gettext_lazy as _
from .models import EditorialAccessInvitation, Variety

class EditorialAccessInvitationForm(forms.Form):
    email = forms.EmailField(label=_('Reviewer or editor email'))
    variety = forms.ModelChoiceField(queryset=Variety.objects.none(), label=_('Spoken variety'))
    capability = forms.ChoiceField(choices=EditorialAccessInvitation.CAPABILITIES, label=_('Limited editorial role'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variety'].queryset = Variety.objects.order_by('code')

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()
