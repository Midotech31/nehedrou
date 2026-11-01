"""Media dropdown labels on fictitious, unqualified records; never speech models."""
import uuid
from html.parser import HTMLParser
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import translation

from catalog.media_labels import media_choice_label
from catalog.models import MediaAsset
from core.models import User
from followup.forms import ItemForm
from qualification.forms import CandidateForm


UNKNOWN = {'fr': 'Inconnu', 'en': 'Unknown', 'ar': 'غير معروف'}


class NoStorageAccess:
    def __getattr__(self, name):
        raise AssertionError('A choice label must not access storage: ' + name)


class MediaOptionDOM(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.select = None
        self.option = None
        self.options = {}
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if tag == 'select':
            self.select = attrs.get('name')
            self.options[self.select] = []
        elif tag == 'option' and self.select is not None:
            self.option = {'attrs': attrs, 'text': ''}
            self.options[self.select].append(self.option)

    def handle_data(self, data):
        if self.option is not None:
            self.option['text'] += data

    def handle_endtag(self, tag):
        if tag == 'option':
            self.option = None
        elif tag == 'select':
            self.select = None


class PureMediaChoiceLabels(SimpleTestCase):
    def asset(self, name):
        asset = MediaAsset(pk=uuid.UUID('11111111-2222-4333-8444-555555555555'),
                           kind='audio', file=name, rights_status='unknown')
        asset.file.storage = NoStorageAccess()
        return asset

    def test_basename_is_independent_of_storage_path_separator_and_interface(self):
        paths = ['private/tenant-secret/signal.wav', r'private\tenant-secret\signal.wav',
                 r'private/tenant-secret\signal.wav']
        for language in ('fr', 'en', 'ar'):
            with translation.override(language):
                for path in paths:
                    with self.subTest(language=language, path=path):
                        self.assertEqual(media_choice_label(self.asset(path)),
                                         'signal.wav · 11111111 · ' + UNKNOWN[language])

    def test_both_form_fields_use_plain_labels_without_sql_or_storage_access(self):
        # SimpleTestCase forbids database queries. Storage raises on any access.
        asset = self.asset('private/tenant-secret/signal.wav')
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                candidate, item = CandidateForm(), ItemForm()
                for field in [candidate.fields['image'], candidate.fields['audio'],
                              item.fields['image_asset'], item.fields['audio_asset']]:
                    label = field.label_from_instance(asset)
                    self.assertEqual(label, 'signal.wav · 11111111 · ' + UNKNOWN[language])
                    self.assertIs(type(label), str)


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RenderedMediaChoices(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user('media-label-fixture', 'media-label@example.test')
        # No file bytes, rights evidence or clinical use are needed for choice
        # rendering. Bulk rows are explicitly unqualified label-only fixtures.
        cls.image = MediaAsset(pk=uuid.UUID('11111111-2222-4333-8444-555555555555'),
            kind='image', file='private/tenant-secret/<img src=x onerror=alert(1)>.png',
            rights='Label fixture only', rights_status='unknown', uploaded_by=owner)
        cls.audio = MediaAsset(pk=uuid.UUID('66666666-7777-4888-8999-000000000000'),
            kind='audio', file=r'private\tenant-secret\signal.wav',
            rights='Label fixture only', rights_status='unknown', uploaded_by=owner)
        MediaAsset.objects.bulk_create([cls.image, cls.audio])

    def forms(self):
        candidate = CandidateForm(initial={'image': self.image.pk, 'audio': self.audio.pk})
        candidate.fields['image'].queryset = MediaAsset.objects.filter(kind='image')
        candidate.fields['audio'].queryset = MediaAsset.objects.filter(kind='audio')
        item = ItemForm(media=MediaAsset.objects.all(), initial={
            'image_asset': self.image.pk, 'audio_asset': self.audio.pk,
        })
        return [(candidate, 'image', 'audio'), (item, 'image_asset', 'audio_asset')]

    def render(self, form):
        with patch.object(default_storage, 'open', side_effect=AssertionError('Choice rendering must not read media')),             patch.object(default_storage, 'exists', side_effect=AssertionError('Choice rendering must not inspect storage')):
            html = form.as_p()
        return html, MediaOptionDOM(html)

    def test_actual_forms_keep_selected_uuids_and_show_localised_unknown_rights(self):
        for language in ('fr', 'en', 'ar'):
            with translation.override(language):
                for form, image_name, audio_name in self.forms():
                    with self.subTest(language=language, form=type(form).__name__):
                        html, dom = self.render(form)
                        for name, asset, basename in [(image_name, self.image, '<img src=x onerror=alert(1)>.png'),
                                                       (audio_name, self.audio, 'signal.wav')]:
                            choices = {row['attrs']['value']: row for row in dom.options[name]}
                            selected = choices[str(asset.pk)]
                            self.assertIn('selected', selected['attrs'])
                            self.assertEqual(selected['text'], basename + ' · ' + str(asset.pk)[:8] + ' · ' + UNKNOWN[language])
                        self.assertNotIn('tenant-secret', html)

    def test_html_escapes_malicious_basename_as_text_in_both_forms(self):
        for language in ('fr', 'en', 'ar'):
            with translation.override(language):
                for form, _, _ in self.forms():
                    with self.subTest(language=language, form=type(form).__name__):
                        html, dom = self.render(form)
                        self.assertIn('&lt;img src=x onerror=alert(1)&gt;.png', html)
                        self.assertNotIn('<img', html)
                        self.assertNotIn('img', dom.tags)
