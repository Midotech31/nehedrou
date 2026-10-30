import uuid
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Activity, Review, MediaAsset

class ActivityForm(forms.ModelForm):
    instructions_fr = forms.CharField(label=_('French caregiver instructions'), widget=forms.Textarea)
    instructions_en = forms.CharField(label=_('English caregiver instructions'), widget=forms.Textarea)
    instructions_ar = forms.CharField(label=_('Arabic caregiver instructions'), widget=forms.Textarea)
    class Meta:
        model = Activity
        fields = ['variety', 'title', 'kind', 'theme', 'response_mode', 'requested_target', 'contrast', 'word_a', 'word_b', 'transcription_a', 'transcription_b', 'image_a', 'image_b', 'audio_a', 'audio_b', 'population', 'limitations', 'practice_guide', 'evidence_sources', 'item_metadata', 'rights', 'is_demo']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .templatetags.content_language import spoken_language, language_direction
        try:
            variety = self.instance.variety if self.instance.variety_id else self.fields['variety'].queryset.filter(pk=self.data.get('variety') if self.is_bound else self.initial.get('variety')).first()
        except (forms.ValidationError, ValueError, TypeError):
            variety = None
        content_language = spoken_language(variety)
        for field in ['word_a', 'word_b']:
            self.fields[field].widget.attrs.update(lang=content_language, dir=language_direction(content_language))
        for field in ['transcription_a', 'transcription_b']:
            self.fields[field].widget.attrs.update(lang='und-fonipa', dir='ltr')

        labels = {'requested_target': _('Requested picture target'), 'kind': _('Activity type'), 'theme': _('Theme'), 'response_mode': _('Response mode'), 'variety': _('Spoken variety'), 'title': _('Activity title'), 'contrast': _('Phonological contrast'), 'word_a': _('First word'), 'word_b': _('Second word'), 'transcription_a': _('First word transcription'), 'transcription_b': _('Second word transcription'), 'image_a': _('First illustration reference'), 'image_b': _('Second illustration reference'), 'audio_a': _('First audio URL'), 'audio_b': _('Second audio URL'), 'population': _('Intended population'), 'limitations': _('Limits and precautions'), 'practice_guide': _('Structured activity guide'), 'evidence_sources': _('Sources and their scope'), 'item_metadata': _('Word meanings, segments, occurrences, variants and familiarity'), 'rights': _('Usage rights'), 'is_demo': _('Demonstration content')}
        for name, label in labels.items():
            self.fields[name].label = label
        for code in ['fr', 'en', 'ar']:

            self.fields['instructions_' + code].initial = self.instance.instructions.get(code, '')
            self.fields['instructions_' + code].widget.attrs.update(lang=code, dir='rtl' if code == 'ar' else 'ltr')
        if self.instance.pk and not self.instance._state.adding:
            self.fields['variety'].disabled = True
    def clean(self):
        data = super().clean()
        self.instance.instructions = {code: data.get('instructions_' + code, '') for code in ['fr', 'en', 'ar']}
        if self.instance._state.adding:
            self.instance.series = self.instance.series or uuid.uuid4()
        return data

class ReviewForm(forms.ModelForm):
    def __init__(self, *args, allowed_kinds=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_kinds is not None:
            self.fields['kind'].choices = [(code, label) for code, label in self.fields['kind'].choices if code in allowed_kinds]

    class Meta:
        model = Review
        fields = ['kind', 'approved', 'note']
        labels = {'requested_target': _('Requested picture target'), 'kind': _('Review type'), 'approved': _('Approved'), 'note': _('Review notes')}

class MediaForm(forms.ModelForm):
    class Meta:
        model = MediaAsset
        fields = ['file', 'kind', 'rights', 'rights_status', 'provenance', 'rights_evidence', 'rights_validity', 'rights_valid_from', 'rights_valid_until']
        labels = {'file': _('File'), 'kind': _('Media type'), 'rights': _('Usage rights'), 'rights_status': _('Rights status'), 'provenance': _('Rights holder, licence, scope, attribution and adult speaker permission'), 'rights_evidence': _('Private rights evidence')}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rights_validity'].required = False
        for name in ['rights_valid_from', 'rights_valid_until']:
            self.fields[name].widget = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')

    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 15 * 1024 * 1024:
            raise forms.ValidationError(_('The file must be smaller than 15 MB.'))
        ext = file.name.rsplit('.', 1)[-1].lower()
        if ext not in ['png','jpg','jpeg','webp','wav','mp3']:
            raise forms.ValidationError(_('Use a PNG, JPEG, WebP, WAV or MP3 file.'))
        from .media_validation import validate_media
        validate_media(file, 'image' if ext in ['png','jpg','jpeg','webp'] else 'audio')
        self._extension = ext
        return file
    def clean(self):
        data = super().clean()
        data['rights_validity'] = data.get('rights_validity') or 'unknown'
        # Optional JSON input must keep the model's empty-object default.
        # This does not qualify an upload: documented rights still require proof.
        if data.get('provenance') is None:
            data['provenance'] = {}
        ext = getattr(self, '_extension', '')
        if data.get('kind') and bool(ext in ['png', 'jpg', 'jpeg', 'webp']) != (data['kind'] == 'image'):
            raise forms.ValidationError(_('The file type must match the selected media kind.'))
        if data.get('file'):
            data['file'].name = uuid.uuid4().hex + '.' + ext
        return data
