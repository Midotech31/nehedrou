from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _
from .models import User
from care.models import Child, Observation, PracticeSession
from catalog.models import Variety

class SignupForm(UserCreationForm):
    practice_name = forms.CharField(label=_('Practice name'), max_length=120)
    class Meta:
        model = User
        fields = ['username', 'email', 'instruction_language', 'practice_name']

class InviteSignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'instruction_language']

class ChildForm(forms.ModelForm):
    varieties = forms.ModelMultipleChoiceField(queryset=Variety.objects.all(), label=_('Spoken varieties'), widget=forms.CheckboxSelectMultiple)
    class Meta:
        model = Child
        fields = ['code', 'age_years', 'varieties']
    def clean_age_years(self):
        value = self.cleaned_data['age_years']
        if not 4 <= value <= 7:
            raise forms.ValidationError(_('The demonstration covers ages 4 to 7.'))
        return value

class ProgramForm(forms.Form):
    title = forms.CharField(label=_('Program title'), max_length=120)
    goal = forms.CharField(label=_('Goal chosen by the clinician'), required=False, max_length=240)
    variety = forms.ModelChoiceField(queryset=Variety.objects.none(), label=_('Spoken variety'))
    activities = forms.ModelMultipleChoiceField(queryset=None, label=_('Activities'), widget=forms.CheckboxSelectMultiple)
    activity_order = forms.CharField(required=False, widget=forms.HiddenInput, max_length=8000)
    guidance = forms.CharField(label=_('Personal instructions'), widget=forms.Textarea, required=False, max_length=2000)
    schedule = forms.CharField(label=_('Frequency and duration chosen by clinician'), required=False, max_length=160)
    practice_start = forms.DateField(label=_('Practice plan starts'), required=False, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), input_formats=['%Y-%m-%d'])
    practice_end = forms.DateField(label=_('Practice plan ends'), required=False, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), input_formats=['%Y-%m-%d'])
    practice_days = forms.MultipleChoiceField(label=_('Days agreed with the family'), required=False, choices=[('0', _('Monday')), ('1', _('Tuesday')), ('2', _('Wednesday')), ('3', _('Thursday')), ('4', _('Friday')), ('5', _('Saturday')), ('6', _('Sunday'))], widget=forms.CheckboxSelectMultiple)
    practice_minutes = forms.IntegerField(label=_('Planned minutes (optional)'), required=False, min_value=1, max_value=120)
    def __init__(self, *args, child, **kwargs):
        from catalog.models import Activity
        from django.conf import settings
        super().__init__(*args, **kwargs)
        self.fields['variety'].queryset = child.varieties.all()
        if not self.is_bound and child.varieties.count() == 1 and not self.initial.get('variety'):
            self.fields['variety'].initial = child.varieties.first()
        qs = Activity.objects.filter(state='published', variety__in=child.varieties.all())
        if not settings.DEMO_MODE:
            qs = qs.filter(is_demo=False)
        from catalog.content_catalog import current_catalog
        qs = current_catalog(qs)
        from .reserves import reserved_activity_ids
        qs = qs.exclude(pk__in=reserved_activity_ids(child, qs.select_related('variety')))
        self.fields['activities'].queryset = qs.select_related('variety').order_by('title', 'pk')
    def clean(self):
        data = super().clean()
        if data.get('variety') and data.get('activities') and any(a.variety_id != data['variety'].pk for a in data['activities']):
            raise forms.ValidationError(_('All activities must match the selected variety.'))
        if data.get('activities'):
            selected = {str(a.pk): a for a in data['activities']}
            order = data.get('activity_order', '').split(',') if data.get('activity_order') else list(selected)
            if len(order) != len(selected) or set(order) != set(selected):
                self.add_error('activity_order', _('The activity order does not match the selection.'))
            else:
                data['activities'] = [selected[pk] for pk in order]
        from .planning import validate_plan
        data['practice_days'] = [int(day) for day in data.get('practice_days', [])]
        if not any(field in self.errors for field in ['practice_start', 'practice_end', 'practice_days', 'practice_minutes']):
            validate_plan(data.get('practice_start'), data.get('practice_end'), data['practice_days'], data.get('practice_minutes'))
        return data

class InvitationForm(forms.Form):
    email = forms.EmailField(label=_('Caregiver email'))

class PracticeForm(forms.Form):
    ticket = forms.CharField(widget=forms.HiddenInput)
    answer = forms.ChoiceField(label=_('Choose the matching image'), choices=[('', '—'), ('a', 'A'), ('b', 'B')], required=False, widget=forms.RadioSelect)
    completion = forms.ChoiceField(label=_('Participation'), choices=[('', _('Choose a response')), ('completed', _('Completed')), ('stopped', _('Stopped'))])
    parent_report = forms.ChoiceField(label=_('Parent report'), choices=[('', _('Choose a response')), ('easy', _('Comfortable')), ('help', _('Needed help')), ('difficult', _('Difficult'))])
    support_used = forms.ChoiceField(label=_('Support reported by the caregiver'), choices=PracticeSession._meta.get_field('support_used').choices, required=False)
    stop_reason = forms.ChoiceField(label=_('Reason for stopping (optional)'), choices=PracticeSession._meta.get_field('stop_reason').choices, required=False)
    comment = forms.CharField(label=_('Parent comment'), widget=forms.Textarea, required=False, max_length=2000)
    def __init__(self, *args, response_mode='matching', **kwargs):
        super().__init__(*args, **kwargs)
        self.response_mode = response_mode
        if response_mode == 'free':
            self.fields['answer'].label = _('Choose a picture freely')
        elif response_mode == 'observation':
            del self.fields['answer']
    def clean(self):
        data = super().clean()
        if data.get('completion') == 'completed' and self.response_mode != 'observation' and not data.get('answer'):
            self.add_error('answer', _('Choose an answer or stop the activity.'))
        if self.response_mode == 'observation' or data.get('completion') == 'stopped':
            data['answer'] = ''
        if data.get('completion') != 'stopped' and data.get('stop_reason'):
            self.add_error('stop_reason', _('A stopping reason belongs to a stopped practice only.'))
        return data

class DemoPracticeForm(PracticeForm):
    """Preview the report UI without accepting identifiers or free-text data."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields['ticket']
        del self.fields['comment']
        del self.fields['support_used']
        del self.fields['stop_reason']

class ObservationForm(forms.ModelForm):
    class Meta:
        model = Observation
        fields = ['text']

class FamilyFeedbackForm(forms.Form):
    text = forms.CharField(label=_('Feedback for the family'), max_length=2000, widget=forms.Textarea,
        help_text=_('This feedback will be visible to the authorized caregivers. Private professional observations stay separate.'))

class HistoryFilterForm(forms.Form):
    kind = forms.ChoiceField(label=_('Record type'), choices=[('reports', _('Parent reports')), ('runs', _('Practice runs')), ('feedback', _('Clinician feedback'))])
    status = forms.ChoiceField(label=_('Status'), required=False, choices=[('', _('All')), ('completed', _('Completed')), ('stopped', _('Stopped'))])
    start = forms.DateField(label=_('From date'), required=False, widget=forms.DateInput(attrs={'type':'date'}))
    end = forms.DateField(label=_('To date'), required=False, widget=forms.DateInput(attrs={'type':'date'}))
    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            raise forms.ValidationError(_('The start date must be before or equal to the end date.'))
        if data.get('kind') == 'feedback':
            data['status'] = ''
        return data

class PreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['instruction_language']

class ReassignForm(forms.Form):
    responsible = forms.ModelChoiceField(queryset=User.objects.none(), label=_('New responsible clinician'))
    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsible'].queryset = User.objects.filter(membership__organization=organization, membership__active=True).distinct()

class PrivacyDecisionForm(forms.Form):
    decision = forms.ChoiceField(label=_('Decision'), choices=[('erase', _('Erase the child record')), ('retain', _('Retain with documented reason'))])
    reason = forms.CharField(label=_('Decision reason'), max_length=500, widget=forms.Textarea)
    confirmation = forms.CharField(label=_('Enter the child pseudonym to confirm'), max_length=60, required=False)
