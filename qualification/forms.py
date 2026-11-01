import uuid
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from catalog.models import Variety
from .models import EvidenceDocument, ReviewerCompetence, AvailabilityDecision, LexicalPack, LexicalCandidate, FamiliarityStudy, PackReview
from .services import evidence_snapshot, REQUIRED_EVIDENCE

class LabelledModelForm(forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        labels = {'variety':_('Spoken variety'),'category':_('Evidence category'),'file':_('File'),'discipline':_('Review type'),'evidence':_('Private supporting document'),'active':_('Declaration remains active'),'module':_('Module'),'status':_('Decision status'),'image':_('Image'),'audio':_('Audio')}
        for key,label in labels.items():
            if key in self.fields:
                self.fields[key].label = label

class EvidenceForm(LabelledModelForm):
    class Meta:
        model = EvidenceDocument
        fields = ['variety', 'title', 'category', 'file', 'source_url', 'provenance', 'validity', 'valid_from', 'valid_until']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['validity'].required = False
        for name in ['valid_from', 'valid_until']:
            self.fields[name].widget = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')

    def clean(self):
        data = super().clean()
        data['validity'] = data.get('validity') or 'unknown'
        return data

    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 15*1024*1024 or file.name.rsplit('.',1)[-1].lower() not in ['pdf','txt','md','csv','json','png','jpg','jpeg']:
            raise ValidationError(_('Use an evidence document under 15 MB: PDF, text, CSV, JSON or image.'))
        file.name = uuid.uuid4().hex + '.' + file.name.rsplit('.',1)[-1].lower()
        return file

class CompetenceForm(LabelledModelForm):
    acknowledge = forms.BooleanField(label=_('I declare this experience honestly; this declaration is not a professional certification.'))
    class Meta:
        model = ReviewerCompetence
        fields = ['variety', 'discipline', 'professional_role', 'experience', 'credential_reference', 'evidence', 'active']

class CompetenceDecisionForm(forms.Form):
    expected_digest = forms.CharField(min_length=64, max_length=64, widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=[('verified', _('Independently checked')), ('rejected', _('Not verified'))], label=_('Verification result'))
    checked_on = forms.DateField(widget=forms.DateInput(attrs={'type':'date'}, format='%Y-%m-%d'),label=_('Verification date'))
    basis = forms.CharField(min_length=20, max_length=2000, widget=forms.Textarea(attrs={'rows': 4}),
                            label=_('Verification basis'),
                            help_text=_('Record what you checked, how, and when. Do not include identity-document numbers or unnecessary personal data.'))

class OpeningTargetForm(forms.Form):
    target = forms.ChoiceField(label=_('Content version to review'))
    def __init__(self, *args, actor, **kwargs):
        from .opening import target_queryset, target_key, target_label
        from .models import MODULES
        super().__init__(*args, **kwargs)
        choices = [('', _('Choose an existing real activity or protocol for this decision.'))]
        for module, _label in MODULES:
            choices.extend((target_key(module, row), target_label(module, row))
                for row in target_queryset(actor, module).select_related('variety').order_by('variety__code', 'title', 'version'))
        self.fields['target'].choices = choices


class AvailabilityForm(forms.Form):
    target = forms.CharField(widget=forms.HiddenInput)
    expected_version = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    status = forms.ChoiceField(label=_('Decision status'), choices=[('blocked', _('Pending requirements')), ('available', _('Available within the documented scope'))])
    scope = forms.CharField(label=_('Authorised purpose, countries and limits'), widget=forms.Textarea)
    reason = forms.CharField(label=_('Decision and justification'), widget=forms.Textarea)
    documents = forms.ModelMultipleChoiceField(queryset=EvidenceDocument.objects.none(), required=False, label=_('Private evidence documents for the five required categories'))
    acknowledge = forms.BooleanField(label=_('I take responsibility for this exact version and documented scope.'))
    def __init__(self, *args, actor, content, module, **kwargs):
        from .opening import target_key
        super().__init__(*args, **kwargs)
        self.fields['target'].initial = target_key(module, content)
        self.fields['expected_version'].initial = content.fingerprint()
        self.fields['documents'].queryset = EvidenceDocument.objects.filter(variety=content.variety, revoked=False)

    def clean(self):
        data = super().clean()
        documents = data.get('documents', [])
        if data.get('status') == 'available':
            categories = [document.category for document in documents]
            if len(categories) != len(REQUIRED_EVIDENCE) or set(categories) != set(REQUIRED_EVIDENCE):
                raise ValidationError(_('Select one document for each required availability category.'))
        return data


class AvailabilityRevocationForm(forms.Form):
    reason = forms.CharField(label=_('Revocation reason'), max_length=2000, widget=forms.Textarea)

class PackForm(LabelledModelForm):
    class Meta:
        model = LexicalPack
        fields = ['variety','title','region','scope','population','indications','limits']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk and not self.instance._state.adding:
            self.fields['variety'].disabled = True
    def clean(self):
        data = super().clean()
        self.instance.series = self.instance.series or uuid.uuid4()
        return data

def lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]

class CandidateForm(LabelledModelForm):
    segment_list = forms.CharField(required=False,label=_('Phonemes in order'),help_text=_('Separate phonemes with spaces. Example: d a r.'))
    target_list = forms.CharField(required=False,widget=forms.Textarea,label=_('Target occurrences'),help_text=_('One target per line: segment number ; phoneme ; initial, medial, final or other. Segment numbering starts at 1.'))
    variant_list = forms.CharField(required=False,widget=forms.Textarea,label=_('Admissible variants and reasons'),help_text=_('One variant per line: IPA form ; reason. Leave empty when no alternative is admitted.'))
    synonym_list = forms.CharField(required=False,widget=forms.Textarea,label=_('Spontaneous alternative names'),help_text=_('One name per line, without participant identities.'))
    class Meta:
        model = LexicalCandidate
        fields = ['word','meaning','ipa','role','provenance','image','audio']
        labels = {'role':_('Training or untrained reserve')}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['segment_list'].initial = ' '.join(self.instance.segments)
        self.fields['target_list'].initial = '\n'.join(f"{item['index']+1} ; {item['phoneme']} ; {item['position']}" for item in self.instance.occurrences)
        self.fields['variant_list'].initial = '\n'.join(f"{item['ipa']} ; {item['reason']}" for item in self.instance.accepted_variants)
        self.fields['synonym_list'].initial = '\n'.join(self.instance.synonyms)
    def clean(self):
        data = super().clean()
        self.instance.segments = data.get('segment_list','').split()
        targets = []
        try:
            for line in lines(data.get('target_list','')):
                number,phoneme,position = [part.strip() for part in line.split(';')]
                targets.append({'index':int(number)-1,'phoneme':phoneme,'position':position})
        except ValueError:
            self.add_error('target_list',_('Use segment number ; phoneme ; position for every target.'))
        variants = []
        try:
            for line in lines(data.get('variant_list','')):
                ipa,reason = [part.strip() for part in line.split(';',1)]
                variants.append({'ipa':ipa,'reason':reason})
        except ValueError:
            self.add_error('variant_list',_('Use IPA form ; reason for every variant.'))
        self.instance.occurrences = targets
        self.instance.accepted_variants = variants
        self.instance.synonyms = lines(data.get('synonym_list',''))
        return data

class FamiliarityForm(LabelledModelForm):
    names = forms.CharField(required=False,widget=forms.Textarea,label=_('Alternative names, without identities'),help_text=_('One name per line, without participant identities.'))
    class Meta:
        model = FamiliarityStudy
        fields = ['method','participants','recognized','evidence']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['names'].initial = '\n'.join(self.instance.alternative_names)
    def clean(self):
        data=super().clean()
        self.instance.alternative_names=lines(data.get('names',''))
        return data

class PackReviewForm(LabelledModelForm):
    expected_digest = forms.CharField(min_length=64, max_length=64, widget=forms.HiddenInput)
    class Meta:
        model = PackReview
        fields = ['kind','approved','note']
        labels = {'kind':_('Review type'),'approved':_('Approved'),'note':_('Review notes')}
