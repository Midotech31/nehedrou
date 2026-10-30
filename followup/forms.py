import re
from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _
from catalog.models import Variety, MediaAsset
from .models import ProbeDefinition
from .validation import target_match_errors, validate_observation_target
from types import SimpleNamespace

POSITION_CHOICES = [('initial', _('Word initial')), ('medial', _('Word medial')), ('final', _('Word final'))]
CONTEXT_HELP = _('Use the same explicit context identifier for equivalent planned contexts, such as isolated_word or carrier_phrase. Different contexts remain separate observations.')


class VariantsField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('widget', forms.Textarea(attrs={'rows': 3, 'dir': 'auto'}))
        kwargs.setdefault('help_text', _('One documented variant per line: identifier | description | IPA (optional). Leave empty when none are admitted.'))
        super().__init__(**kwargs)

    def clean(self, value):
        text = super().clean(value)
        rows, seen = [], set()
        for line in text.splitlines():
            if not line.strip():
                continue
            pieces = [piece.strip() for piece in line.split('|')]
            if len(pieces) not in (2, 3) or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', pieces[0]) or not pieces[1] or pieces[0] in seen:
                raise forms.ValidationError(_('Each variant needs a unique identifier and a description.'))
            row = {'id': pieces[0], 'label': pieces[1]}
            if len(pieces) == 3 and pieces[2]:
                row['ipa'] = pieces[2]
            rows.append(row)
            seen.add(pieces[0])
        return rows

    def prepare_value(self, value):
        if isinstance(value, list):
            return '\n'.join(' | '.join([str(row.get('id', '')), str(row.get('label', '')), str(row.get('ipa', ''))]).rstrip(' |') for row in value)
        return value


class GoalForm(forms.Form):
    variety = forms.ModelChoiceField(queryset=Variety.objects.none(), label=_('Treatment variety'))
    probe_definition = forms.ModelChoiceField(queryset=ProbeDefinition.objects.none(), label=_('Protocol version to reserve for follow-up'), required=False, help_text=_('Choosing a protocol reserves its untrained words before family practice. It does not authorize real administration.'))
    external_assessment_status = forms.ChoiceField(label=_('External assessment status'), choices=[('pending', _('Pending')), ('confirmed', _('Already assessed by the responsible professional')), ('not_recorded', _('Not recorded'))])
    external_assessment_note = forms.CharField(label=_('Assessment context'), required=False, widget=forms.Textarea(attrs={'rows': 3}), help_text=_('Document the assessment context without copying protected test items.'))
    target_phoneme = forms.CharField(label=_('Target phoneme'), max_length=80, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    contrast = forms.CharField(label=_('Contrast, when relevant'), max_length=100, required=False, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    target_position = forms.ChoiceField(label=_('Target position'), choices=POSITION_CHOICES)
    context_key = forms.RegexField(label=_('Structured target context'), regex=r'^[a-z0-9][a-z0-9_-]{0,99}$', max_length=100, help_text=CONTEXT_HELP)
    context = forms.CharField(label=_('Lexical and communicative context'), widget=forms.Textarea(attrs={'rows': 2}), required=False)
    rationale = forms.CharField(label=_('Clinical rationale'), widget=forms.Textarea(attrs={'rows': 3}))
    expected_realization = forms.CharField(label=_('Expected realization'), widget=forms.Textarea(attrs={'rows': 2}))
    accepted_variants = VariantsField(label=_('Documented acceptable variants'))
    functional_goal = forms.CharField(label=_('Functional goal'), widget=forms.Textarea(attrs={'rows': 2}))
    review_date = forms.DateField(label=_('Next professional review'), required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, child, definitions=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variety'].queryset = child.varieties.all()
        self.fields['probe_definition'].queryset = definitions if definitions is not None else ProbeDefinition.objects.none()

    def clean(self):
        data = super().clean()
        if data.get('target_position') and data.get('context_key'):
            data['target_scope'] = {'position': data['target_position'], 'context': data['context_key']}
        if data.get('probe_definition') and data.get('variety') and data.get('target_phoneme') and data.get('target_scope'):
            objective = SimpleNamespace(variety_id=data['variety'].pk, target_phoneme=data['target_phoneme'], target_scope=data['target_scope'])
            for error in target_match_errors(objective, data['probe_definition']):
                self.add_error('probe_definition', error)
        return data


RIGHTS_CHOICES = [('unknown', _('Documentation missing')), ('original_documented', _('Original material with documented rights')), ('open_commercial_compatible', _('Documented compatible open licence')), ('permission_required', _('Permission required')), ('excluded', _('Excluded from use'))]


class DefinitionForm(forms.Form):
    title = forms.CharField(label=_('Protocol title'), max_length=160)
    variety = forms.ModelChoiceField(queryset=Variety.objects.all(), label=_('Spoken variety'))
    protocol = forms.CharField(label=_('Original protocol and permitted support'), widget=forms.Textarea(attrs={'rows': 4}))
    task = forms.CharField(label=_('Elicitation task'), max_length=160)
    target_phoneme = forms.CharField(label=_('Target phoneme'), max_length=80, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    target_position = forms.ChoiceField(label=_('Target position'), choices=POSITION_CHOICES)
    context_key = forms.RegexField(label=_('Structured target context'), regex=r'^[a-z0-9][a-z0-9_-]{0,99}$', max_length=100, help_text=CONTEXT_HELP)
    rights = forms.CharField(label=_('Rights and provenance documentation'), required=False, widget=forms.Textarea(attrs={'rows': 3}))
    rights_status = forms.ChoiceField(label=_('Rights status'), choices=RIGHTS_CHOICES)
    evidence = forms.JSONField(label=_('Protocol evidence references'), required=False, initial=dict, widget=forms.Textarea(attrs={'rows': 4, 'dir': 'ltr'}), help_text=_('Professional JSON object. Keep rights_evidence, familiarity_evidence and linguistic_evidence as objects containing the exact document id and sha256. Missing evidence keeps real use blocked.'))
    is_demo = forms.BooleanField(label=_('Fictitious demonstration protocol'), required=False, help_text=_('A fictitious protocol can only be used with fictional demonstration profiles.'))

    def __init__(self, *args, definition=None, **kwargs):
        if definition:
            kwargs.setdefault('initial', {name: (definition.target_scope.get('context', '') if name == 'context_key' else getattr(definition, name)) for name in self.base_fields})
        super().__init__(*args, **kwargs)
        if definition:
            self.fields['variety'].disabled = True
            self.fields['is_demo'].disabled = True

    def clean(self):
        data = super().clean()
        if data.get('target_position') and data.get('context_key'):
            data['target_scope'] = {'position': data['target_position'], 'context': data['context_key']}
        return data

    def clean_evidence(self):
        evidence = self.cleaned_data['evidence'] or {}
        if not isinstance(evidence, dict):
            raise forms.ValidationError(_('Protocol evidence must be a JSON object.'))
        return evidence


EXPOSURE_CHOICES = [('trained', _('Trained word')), ('reserved', _('Reserved, untrained word')), ('uncertain', _('Exposure uncertain'))]


class SegmentsField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('widget', forms.Textarea(attrs={'rows': 3, 'dir': 'ltr'}))
        kwargs.setdefault('help_text', _('Enter one phoneme per line, in order. A multicharacter IPA phoneme remains one segment. Do not split the IPA string automatically.'))
        super().__init__(**kwargs)

    def clean(self, value):
        return [line.strip() for line in super().clean(value).splitlines() if line.strip()]

    def prepare_value(self, value):
        return '\n'.join(value) if isinstance(value, list) else value


class MediaChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.file.name.rsplit('/', 1)[-1]} · {str(obj.pk)[:8]} · {obj.get_rights_status_display()}"


class ItemForm(forms.Form):
    original_id = forms.CharField(required=False, disabled=True, widget=forms.HiddenInput)
    id = forms.SlugField(label=_('Stable item identifier'), max_length=100)
    word = forms.CharField(label=_('Word'), max_length=120, widget=forms.TextInput(attrs={'dir': 'auto'}))
    ipa = forms.CharField(label=_('IPA transcription proposed for review'), max_length=160, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    meaning = forms.CharField(label=_('Meaning and intended image interpretation'), max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 2, 'dir': 'auto'}))
    segments = SegmentsField(label=_('Explicit phonemic segments'))
    target_definition = forms.CharField(label=_('Exact target occurrence'), widget=forms.Textarea(attrs={'rows': 2}))
    target_occurrence_index = forms.IntegerField(label=_('Occurrence index, starting at zero'), min_value=0, initial=0)
    target_occurrences = forms.JSONField(label=_('Documented target occurrences'), required=False, widget=forms.Textarea(attrs={'rows': 3, 'dir': 'ltr'}), help_text=_('Professional JSON list: [{"index": 0, "phoneme": "p", "position": "initial", "context": "..."}]. The index refers to the explicit segment list. Leave empty while the draft awaits human documentation.'))
    selected_attempt = forms.IntegerField(label=_('Attempt retained before administration'), min_value=1, max_value=20, initial=1)
    exposure_plan = forms.ChoiceField(label=_('Planned exposure'), choices=EXPOSURE_CHOICES, initial='trained')
    accepted_variants = VariantsField(label=_('Documented acceptable variants'))
    image_asset = MediaChoiceField(label=_('Image media reference'), queryset=MediaAsset.objects.none(), required=False, help_text=_('Choose an existing image. Upload and document its rights in the editorial media library first.'))
    audio_asset = MediaChoiceField(label=_('Audio media reference'), queryset=MediaAsset.objects.none(), required=False)
    familiarity_verified = forms.BooleanField(label=_('Human word and image familiarity documented'), required=False)
    familiarity_note = forms.CharField(label=_('Familiarity evidence and limitations'), max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    reviewed = forms.BooleanField(label=_('Human linguistic item review documented'), required=False)
    review_note = forms.CharField(label=_('Item review evidence and limitations'), max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, media=None, **kwargs):
        super().__init__(*args, **kwargs)
        if media is not None:
            self.fields['image_asset'].queryset = media.filter(kind='image')
            self.fields['audio_asset'].queryset = media.filter(kind='audio')

    def clean_target_occurrences(self):
        rows = self.cleaned_data['target_occurrences'] or []
        if not isinstance(rows, list):
            raise forms.ValidationError(_('Target occurrences must be a JSON list.'))
        return rows


class UniqueItemsFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = [form.cleaned_data for form in self.forms if form.cleaned_data and not form.cleaned_data.get('DELETE')]
        if not rows or len({row['id'] for row in rows}) != len(rows):
            raise forms.ValidationError(_('Provide at least one item, with a unique identifier for every item.'))


ItemFormSet = formset_factory(ItemForm, formset=UniqueItemsFormSet, extra=2, can_delete=True, max_num=60, validate_max=True)


class ReviewForm(forms.Form):
    kind = forms.ChoiceField(label=_('Review discipline'))
    competence = forms.CharField(label=_('Declared competence for this spoken variety'), widget=forms.Textarea(attrs={'rows': 2}))
    approved = forms.BooleanField(label=_('Internal review accepted for this exact version'), required=False)
    note = forms.CharField(label=_('Review note and limitations'), widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, kinds, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {'clinical': _('Clinical review'), 'linguistic': _('Linguistic review')}
        self.fields['kind'].choices = [(kind, labels[kind]) for kind in kinds]


class ConditionsForm(forms.Form):
    definition = forms.ModelChoiceField(queryset=ProbeDefinition.objects.none(), label=_('Exact protocol version'))
    observation_scope = forms.ChoiceField(label=_('Observation context'), choices=[('goal', _('Goal context')), ('alternate_context', _('Separate context observation'))])
    alternate_context_label = forms.CharField(label=_('Separate context name'), max_length=160, required=False)
    alternate_context_reason = forms.CharField(label=_('Reason for observing another context'), max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    place = forms.CharField(label=_('Setting'), required=False)
    task = forms.ChoiceField(label=_('Planned task'), choices=[('naming', _('Picture naming')), ('semantic_cue', _('Naming with semantic cue')), ('lexical_choice', _('Lexical choice')), ('imitation', _('Imitation'))])
    fatigue = forms.CharField(label=_('Fatigue and wellbeing'), required=False)
    noise = forms.CharField(label=_('Noise and listening conditions'), required=False)
    interruption = forms.CharField(label=_('Interruption or stopping conditions'), required=False)
    instructions = forms.CharField(label=_('Instructions given at the start'), widget=forms.Textarea(attrs={'rows': 2}))
    audio_equipment = forms.CharField(label=_('Audio equipment, if used'), required=False)
    attempt_rule = forms.CharField(label=_('Attempt retained, decided before presentation'), help_text=_('Specify the retained attempt in advance. Do not retrospectively choose the best response.'))
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, definitions, goal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal = goal
        self.fields['definition'].queryset = definitions

    def clean(self):
        data = super().clean()
        if self.goal and data.get('definition') and data.get('observation_scope'):
            validate_observation_target(self.goal, data['definition'], data['observation_scope'], data.get('alternate_context_label', ''), data.get('alternate_context_reason', ''))
        return data


class FamiliarityForm(forms.Form):
    def __init__(self, *args, items, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items
        for number, item in enumerate(items):
            self.fields[f'known_{number}'] = forms.ChoiceField(label=_('Image and word understood: %(word)s') % {'word': item['word']}, choices=[('uncertain', _('Not yet confirmed')), ('familiar', _('Image recognized and word understood')), ('unfamiliar', _('Unfamiliar; replace or document separately'))])
            self.fields[f'note_{number}'] = forms.CharField(label=_('Familiarity note'), required=False)

    def result(self):
        return {item['id']: {'familiar': self.cleaned_data[f'known_{number}'] == 'familiar', 'note': self.cleaned_data[f'note_{number}']} for number, item in enumerate(self.items)}


CODE_CHOICES = [('TARGET_ACCEPTABLE', _('Target acceptable')), ('VARIANT_ACCEPTABLE', _('Documented variant acceptable')), ('TARGET_INCORRECT', _('Target incorrect in an audible attempt')), ('NOT_SCORABLE', _('Not scorable')), ('NOT_PRESENTED', _('Not presented'))]
ELICITATION_CHOICES = [('naming', _('Picture naming')), ('semantic_cue', _('Semantic cue')), ('lexical_choice', _('Lexical choice')), ('imitation', _('Imitation'))]


class RatingForm(forms.Form):
    code = forms.ChoiceField(label=_('Occurrence rating'), choices=CODE_CHOICES)
    attempt_index = forms.IntegerField(label=_('Retained attempt number'), min_value=1, initial=1)
    elicitation = forms.ChoiceField(label=_('Actual elicitation'), choices=ELICITATION_CHOICES)
    assistance = forms.CharField(label=_('Support actually provided'), required=False)
    transcription = forms.CharField(label=_('Optional production transcription'), required=False, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    variant_id = forms.ChoiceField(label=_('Documented variant'), required=False)
    attempted_expected_word = forms.BooleanField(label=_('The expected word was audibly attempted'), required=False)
    target_identifiable = forms.BooleanField(label=_('The target is identifiable and scorable'), required=False)
    error_type = forms.ChoiceField(label=_('Error type'), required=False, choices=[('', '—'), ('substitution', _('Substitution')), ('omission', _('Audible target omission')), ('distortion', _('Distortion')), ('other', _('Other scorable error'))])
    exclusion_reason = forms.CharField(label=_('Reason for exclusion'), required=False, widget=forms.Textarea(attrs={'rows': 2}))
    reason = forms.CharField(label=_('Reason for correction'), required=False, widget=forms.Textarea(attrs={'rows': 2}), help_text=_('Changing an existing rating requires a reason and preserves its history.'))

    def __init__(self, *args, variants, existing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variant_id'].choices = [('', '—')] + [(row['id'], row['label']) for row in variants]
        self.fields['reason'].required = existing


class FinalizeForm(forms.Form):
    reviewed = forms.BooleanField(label=_('I reviewed the retained attempts, support, exclusions and conditions'))


class ShareForm(forms.Form):
    text = forms.CharField(label=_('Text explicitly shared with the family'), widget=forms.Textarea(attrs={'rows': 5}), help_text=_('Only this text is shared. Do not include reserved words, raw ratings or private notes.'))
    scope_confirmed = forms.BooleanField(label=_('I checked the scope and content of this family summary'))


class CoachingForm(forms.Form):
    instruction_language = forms.ChoiceField(label=_('Adult instruction language'), choices=[('fr', 'Français'), ('en', 'English'), ('ar', 'العربية')], help_text=_('The clinician writes the instructions in this language. Changing interface language does not translate free-text clinical instructions.'))
    variety = forms.ModelChoiceField(queryset=Variety.objects.none(), label=_('Practice variety'))
    instructions = forms.CharField(label=_('Parent instructions'), widget=forms.Textarea(attrs={'rows': 4}))
    example = forms.CharField(label=_('Example shown by the clinician'), widget=forms.Textarea(attrs={'rows': 3}))
    accompanied_trial = forms.CharField(label=_('Accompanied practice trial'), widget=forms.Textarea(attrs={'rows': 3}))
    understanding_checked = forms.BooleanField(label=_('The clinician checked caregiver understanding'), required=False, help_text=_('This is recorded by the responsible clinician after checking; it is not a caregiver self-approval.'))
    clinician_note = forms.CharField(label=_('Private clinician note'), required=False, widget=forms.Textarea(attrs={'rows': 2}))
    next_review = forms.DateField(label=_('Next review'), required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, child, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variety'].queryset = child.varieties.all()


class HomeFeedbackForm(forms.Form):
    participation = forms.ChoiceField(label=_('Participation'), choices=[('completed', _('Completed')), ('partial', _('Partial')), ('stopped', _('Stopped'))])
    support_used = forms.CharField(label=_('Support used during practice'), max_length=1000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    difficulty = forms.ChoiceField(label=_('Difficulty reported by the caregiver'), choices=[('easy', _('Comfortable')), ('help', _('Help needed')), ('difficult', _('Difficult'))])
    stop_reason = forms.CharField(label=_('Reason for stopping'), max_length=1000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    comment = forms.CharField(label=_('Other information for the clinician'), max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    key = forms.UUIDField(widget=forms.HiddenInput)

    def clean(self):
        data = super().clean()
        if data.get('participation') == 'stopped' and not data.get('stop_reason'):
            self.add_error('stop_reason', _('Explain why practice stopped.'))
        return data


class ExposureForm(forms.Form):
    variety = forms.ModelChoiceField(queryset=Variety.objects.none(), label=_('Treatment variety'))
    word = forms.CharField(label=_('Word'), max_length=120, widget=forms.TextInput(attrs={'dir': 'auto'}))
    status = forms.ChoiceField(label=_('External word exposure'), choices=[('trained', _('Trained word')), ('untrained', _('Untrained word')), ('uncertain', _('Exposure uncertain'))])
    note = forms.CharField(label=_('Exposure context and source'), max_length=2000, widget=forms.Textarea(attrs={'rows': 3}))
    occurred_at = forms.DateTimeField(label=_('Exposure date and time'), required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'), help_text=_('Leave empty to record the current time.'))

    def __init__(self, *args, child, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variety'].queryset = child.varieties.all()
