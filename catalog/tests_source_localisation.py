"""Regression tests for exact, presentation-only bibliographic translations."""

import json
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.html import conditional_escape
from django.utils.translation import override

from catalog.templatetags.content_language import localized_source_scope, source_declarations


class SourceScopeLocalisationTests(SimpleTestCase):
    def test_all_shipped_reference_notes_display_in_each_supported_language(self):
        root = Path(settings.BASE_DIR) / 'docs'
        notes = set()
        for filename in ('arabic-library-v1.json', 'arabic-library-v2.json', 'catalog-candidates.json'):
            document = json.loads((root / filename).read_text(encoding='utf-8'))
            rows = document['activities'] if isinstance(document, dict) else document
            notes.update((source['url'], source['scope']) for row in rows for source in row['evidence_sources'])

        self.assertEqual(notes, source_declarations().keys())
        for url, scope in notes:
            source = {'url': url, 'scope': scope}
            for language in ('fr', 'en', 'ar'):
                with self.subTest(url=url, language=language):
                    rendered = localized_source_scope(source, language)
                    self.assertEqual(rendered['language'], language)
                    self.assertTrue(rendered['text'].strip())
            self.assertEqual(source, {'url': url, 'scope': scope})

    def test_localized_scope_uses_guide_language_and_preserves_reference_title(self):
        url = 'https://www.asha.org/practice-portal/professional-issues/multilingual-service-delivery/'
        source = {
            'url': url,
            'title': 'ASHA — Multilingual Service Delivery',
            'title_language': 'en',
            'scope': ('Cadre professionnel de prise en compte des langues, dialectes et usages familiaux. '
                      'Ne valide ni ces mots ni les illustrations ni l’efficacité de Nehedrou.'),
        }
        for language, direction in (('ar', 'rtl'), ('en', 'ltr'), ('fr', 'ltr')):
            with self.subTest(language=language), override('fr'):
                html = render_to_string('content_guide.html', {'guide': {'language': language}, 'sources': [source]})
                text = conditional_escape(localized_source_scope(source, language)['text'])
                self.assertIn(f'<p lang="{language}" dir="{direction}">{text}</p>', html)
                self.assertIn(f'href="{url}" rel="noreferrer" lang="en" dir="ltr">{source["title"]}</a>', html)

        with override('ar'):
            translation = conditional_escape(localized_source_scope(source, 'ar')['text'])
            html = render_to_string('content_guide.html', {'sources': [source]})
        self.assertIn(f'<p lang="ar" dir="rtl">{translation}</p>', html)

    def test_editorial_edits_do_not_inherit_a_translation(self):
        declaration = next(iter(source_declarations().values()))
        source = {'url': declaration['url'], 'scope': declaration['scope']}
        modified = dict(source, scope=source['scope'] + ' Note personnelle.')
        self.assertEqual(localized_source_scope(modified, 'ar'), {'text': modified['scope'], 'language': 'und'})

        changed_url = dict(source, url='https://example.test/other-source')
        self.assertEqual(localized_source_scope(changed_url, 'ar'), {'text': source['scope'], 'language': 'und'})

        explicitly_declared = dict(source, scope_language='en')
        self.assertEqual(localized_source_scope(explicitly_declared, 'ar'),
                         {'text': source['scope'], 'language': 'en'})
