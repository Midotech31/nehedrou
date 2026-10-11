"""Human-readable draft authoring; publication safeguards stay on Activity."""
import copy
import uuid
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from .models import Activity, MediaAsset
from .content_validation import TEXT_FIELDS, STEP_FIELDS

GUIDE_LABELS = {
    'objective': _('Activity objective'), 'audience': _('Who this activity is for'),
    'discover': _('Discover together'), 'listen': _('Listening instructions'),
    'exchange': _('Interaction and practice'), 'support': _('Possible help'),
    'limits': _('Limits of this activity'), 'review_notes': _('Points for professional review'),
}
LANGUAGE_LABELS = {'fr': _('French'), 'en': _('English'), 'ar': _('Arabic')}


class ActivityAuthoringForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ['variety', 'title', 'kind', 'theme', 'response_mode', 'requested_target',
                  'contrast', 'word_a', 'word_b', 'transcription_a', 'transcription_b',
                  'image_a', 'image_b', 'audio_a', 'audio_b', 'population', 'limitations', 'rights', 'is_demo']

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        from .forms import ActivityForm
        labels = ActivityForm(instance=self.instance)
        for name in self.fields:
            self.fields[name].label = labels.fields[name].label
        for name in ['word_a', 'word_b', 'meaning_a', 'meaning_b']:
            if name in self.fields: self.fields[name].widget.attrs['dir'] = 'auto'
        self.fields['contrast'].label = _('Target or theme')
        self.fields['contrast'].help_text = _('For vocabulary or conversation, describe the theme; do not claim a minimal pair.')
        self.fields['population'].widget = forms.Textarea(attrs={'rows': 3})
        self.fields['limitations'].widget = forms.Textarea(attrs={'rows': 3})
        self.fields['rights'].widget = forms.Textarea(attrs={'rows': 3})
        if self.instance.pk and not self.instance._state.adding:
            self.fields['variety'].disabled = True
        media = MediaAsset.objects.filter(uploaded_by=actor)
        # Shared media may be reused only through an activity in the actor's scope.
        if actor.is_superuser:
            media = MediaAsset.objects.all()
        else:
            from .views import editorial_activities
            from django.db.models import Q
            scoped = editorial_activities(actor)
            image_ids = [ref[len('editorial/asset-'):] for ref in list(scoped.values_list('image_a', flat=True)) + list(scoped.values_list('image_b', flat=True)) if ref.startswith('editorial/asset-')]
            audio_ids = []
            from urllib.parse import urlsplit
            for ref in list(scoped.values_list('audio_a', flat=True)) + list(scoped.values_list('audio_b', flat=True)):
                parts = urlsplit(ref).path.strip('/').split('/')
                if len(parts) == 3 and parts[1] == 'media':
                    try: audio_ids.append(uuid.UUID(parts[2]))
                    except ValueError: pass
            valid_images = []
            for value in image_ids:
                try: valid_images.append(uuid.UUID(value))
                except ValueError: pass
            media = MediaAsset.objects.filter(Q(uploaded_by=actor) | Q(pk__in=valid_images + audio_ids)).distinct()
        for side in ['a', 'b']:
            self.fields['choose_image_' + side] = forms.ModelChoiceField(
                label=_('Choose an uploaded illustration'), queryset=media.filter(kind='image').order_by('-created_at'), required=False)
            self.fields['choose_audio_' + side] = forms.ModelChoiceField(
                label=_('Choose an uploaded audio'), queryset=media.filter(kind='audio').order_by('-created_at'), required=False)
            for media_kind in ['image', 'audio']:
                self.fields[f'choose_{media_kind}_{side}'].label_from_instance = lambda asset: asset.created_at.strftime('%Y-%m-%d') + ' · ' + asset.rights[:80] + ' · ' + str(asset.pk)[:8]
            for key, label in [('meaning', _('Intended meaning')), ('segments', _('Ordered phonemes')), ('targets', _('Target phoneme indices')), ('familiarity', _('Familiarity in the child’s environment'))]:
                initial = self.instance.item_metadata.get(side, {})
                value = initial.get(key, '')
                if key == 'familiarity' and isinstance(value, dict): value = value.get('note', '')
                if key == 'segments': value = ' '.join(initial.get('segments', []))
                if key == 'targets': value = ', '.join(str(x['index']) for x in initial.get('target_occurrences', []))
                self.fields[f'{key}_{side}'] = forms.CharField(label=label, required=False, initial=value, max_length=2000)
            self.fields[f'segments_{side}'].help_text = _('Separate phonemes with spaces, for example k a t. This does not verify the transcription.')
            self.fields[f'targets_{side}'].help_text = _('Indices start at 0; separate multiple indices with commas. Example: 0 for the first phoneme.')
        self.language_sections = []
        for code, label in LANGUAGE_LABELS.items():
            self.fields['instructions_' + code] = forms.CharField(label=labels.fields['instructions_' + code].label,
                required=False, widget=forms.Textarea(attrs={'rows': 3, 'lang': code, 'dir': 'rtl' if code == 'ar' else 'ltr'}),
                initial=self.instance.instructions.get(code, ''), max_length=6000)
            fields = []
            existing = self.instance.practice_guide.get(code, {})
            for key, field_label in GUIDE_LABELS.items():
                value = existing.get(key, '')
                if key in STEP_FIELDS: value = '\n'.join(value) if isinstance(value, list) else ''
                name = f'guide_{code}_{key}'
                self.fields[name] = forms.CharField(label=field_label, required=False, max_length=16000,
                    widget=forms.Textarea(attrs={'rows': 3, 'lang': code, 'dir': 'rtl' if code == 'ar' else 'ltr'}), initial=value)
                if key in STEP_FIELDS: self.fields[name].help_text = _('One instruction per line; up to eight lines.')
                fields.append(self[name])
            self.language_sections.append({'code': code, 'label': label, 'instructions': self['instructions_' + code], 'fields': fields})
        self.source_rows = []
        for index in range(12):
            existing = self.instance.evidence_sources[index] if index < len(self.instance.evidence_sources) else {}
            row = []
            for key, label in [('title', _('Source title')), ('url', _('Source HTTPS link')), ('scope', _('What this source supports'))]:
                name = f'source_{index}_{key}'
                field = forms.URLField if key == 'url' else forms.CharField
                self.fields[name] = field(label=label, required=False, initial=existing.get(key, ''), max_length=2000)
                row.append(self[name])
            self.source_rows.append(row)

    def clean(self):
        data = super().clean()
        self.instance.series = self.instance.series or uuid.uuid4()
        self.instance.instructions = {code: data.get('instructions_' + code, '') for code in LANGUAGE_LABELS}
        guide = {}
        for code in LANGUAGE_LABELS:
            values = {key: data.get(f'guide_{code}_{key}', '') for key in GUIDE_LABELS}
            if not any(values.values()): continue
            for key, value in values.items():
                if not value:
                    self.add_error(f'guide_{code}_{key}', _('Complete each guide section in this language, or leave this entire guide blank.'))
            if all(values.values()):
                guide[code] = {key: [line.strip() for line in value.splitlines() if line.strip()] if key in STEP_FIELDS else value for key, value in values.items()}
        self.instance.practice_guide = guide
        sources = []
        for index in range(12):
            row = {key: data.get(f'source_{index}_{key}', '') for key in ['title', 'url', 'scope']}
            if not any(row.values()): continue
            if not all(row.values()):
                for key, value in row.items():
                    if not value: self.add_error(f'source_{index}_{key}', _('Complete the title, HTTPS link and scope of each source.'))
            elif not row['url'].startswith('https://'):
                self.add_error(f'source_{index}_url', _('Use an HTTPS source link.'))
            else: sources.append(row)
        self.instance.evidence_sources = sources
        metadata = copy.deepcopy(self.instance.item_metadata)
        has_items = bool(metadata) or any(data.get(f'{key}_{side}') for key in ['meaning', 'segments', 'targets', 'familiarity'] for side in ['a', 'b'])
        if has_items:
            for side in ['a', 'b']:
                item = metadata.setdefault(side, {})
                item['meaning'] = data.get('meaning_' + side, '')
                if isinstance(item.get('familiarity'), dict):
                    item['familiarity']['note'] = data.get('familiarity_' + side, '')
                else:
                    item['familiarity'] = data.get('familiarity_' + side, '')
                item['segments'] = data.get('segments_' + side, '').split()
                targets = data.get('targets_' + side, '').replace(',', ' ').split()
                occurrences = []
                previous = {x['index']: x for x in item.get('target_occurrences', [])}
                try:
                    indices = [int(value) for value in targets]
                    if len(set(indices)) != len(indices) or any(index < 0 or index >= len(item['segments']) for index in indices): raise ValueError
                    for index in indices:
                        phoneme = item['segments'][index]
                        position = 'initial' if index == 0 else 'final' if index == len(item['segments']) - 1 else 'medial'
                        if index in previous and previous[index]['phoneme'] == phoneme: position = previous[index]['position']
                        occurrences.append({'index': index, 'phoneme': phoneme, 'position': position})
                except ValueError:
                    self.add_error('targets_' + side, _('Use unique indices that exist in the ordered phoneme list.'))
                item['target_occurrences'] = occurrences
                item.setdefault('accepted_variants', [])
        self.instance.item_metadata = metadata
        for side in ['a', 'b']:
            image, audio = data.get('choose_image_' + side), data.get('choose_audio_' + side)
            if image: data['image_' + side] = 'editorial/asset-' + str(image.pk)
            if audio:
                from django.urls import reverse
                data['audio_' + side] = settings.PUBLIC_ORIGIN.rstrip('/') + reverse('editorial_media', args=[audio.pk])
        return data
