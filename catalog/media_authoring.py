"""Rights data entered as plain fields; human evidence requirements are unchanged."""
from django import forms
from django.utils.translation import gettext_lazy as _
from .forms import MediaForm

RIGHTS_LABELS = {
    'holder':_('Rights holder'), 'licence':_('Licence or permission'),
    'permitted_use':_('Permitted use'), 'territory':_('Territory'),
    'duration':_('Permission duration'), 'attribution':_('Required attribution'),
    'adult_speaker_permission':_('Adult speaker permission'),
}

class MediaAuthoringForm(MediaForm):
    class Meta(MediaForm.Meta):
        fields = [name for name in MediaForm.Meta.fields if name != 'provenance']

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields.pop('provenance', None)
        for name,label in RIGHTS_LABELS.items():
            self.fields['rights_'+name]=forms.CharField(label=label,required=False,max_length=2000,widget=forms.Textarea(attrs={'rows':2,'dir':'auto'}))
        self.fields['file'].widget.attrs['accept']='.png,.jpg,.jpeg,.wav,.mp3'
        self.fields['rights_adult_speaker_permission'].help_text=_('For an adult recording, document consent and permitted uses. Upload the supporting rights document through the qualification workspace.')
    def clean(self):
        data=super().clean()
        data['provenance']={name:data.get('rights_'+name,'') for name in RIGHTS_LABELS if data.get('rights_'+name)}
        self.instance.provenance = data['provenance']
        return data
