"""Plain rights and speech provenance, without claiming a human approval."""
from django import forms
from django.utils.translation import gettext_lazy as _
from .forms import MediaForm
from .models import Variety

RIGHTS_LABELS = {
    'holder':_('Rights holder'), 'licence':_('Licence or permission'),
    'permitted_use':_('Permitted use'), 'territory':_('Territory'),
    'duration':_('Permission duration'), 'attribution':_('Required attribution'),
    'adult_speaker_permission':_('Adult speaker permission'),
}

class MediaAuthoringForm(MediaForm):
    class Meta(MediaForm.Meta):
        fields = [name for name in MediaForm.Meta.fields if name != 'provenance']

    def __init__(self,*args,actor=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields.pop('provenance', None)
        choices = Variety.objects.all() if actor and actor.is_superuser else Variety.objects.filter(editorialgrant__user=actor,editorialgrant__edit=True).distinct() if actor else Variety.objects.none()
        self.fields['audio_variety'] = forms.ModelChoiceField(label=_('Recording language and variety'),queryset=choices,required=False)
        self.fields['audio_text'] = forms.CharField(label=_('Exact spoken word or phrase'),max_length=160,required=False,widget=forms.TextInput(attrs={'dir':'auto'}))
        self.fields['audio_source'] = forms.ChoiceField(label=_('Voice source'),choices=[('',_('Select voice source')),('human',_('Adult human recording')),('synthetic',_('Synthetic speech')),('unspecified',_('Source to document'))],required=False)
        self.fields['audio_region'] = forms.CharField(label=_('Regional variety or accent notes'),max_length=300,required=False,widget=forms.TextInput(attrs={'dir':'auto'}))
        for name,label in RIGHTS_LABELS.items():
            self.fields['rights_'+name]=forms.CharField(label=label,required=False,max_length=2000,widget=forms.Textarea(attrs={'rows':2,'dir':'auto'}))
        self.fields['file'].widget.attrs['accept']='.png,.jpg,.jpeg,.wav,.mp3'
        self.fields['rights_adult_speaker_permission'].help_text=_('For an adult recording, document consent and permitted uses. Upload the supporting rights document through the qualification workspace.')

    def clean(self):
        data=super().clean()
        profile={}
        if data.get('kind')=='audio':
            for name in ['audio_variety','audio_text','audio_source']:
                if not data.get(name): self.add_error(name,_('Document the variety, exact spoken text and voice source before saving audio.'))
            if data.get('audio_variety'):
                profile={'variety':data['audio_variety'].code,'text':data.get('audio_text',''),
                         'source':data.get('audio_source',''),'region':data.get('audio_region','')}
        data['provenance']={name:data.get('rights_'+name,'') for name in RIGHTS_LABELS if data.get('rights_'+name)}
        if profile: data['provenance']['audio']=profile
        self.instance.provenance = data['provenance']
        return data
