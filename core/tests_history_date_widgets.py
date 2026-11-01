"""Native date inputs must retain ISO values independently of interface language."""
from datetime import date
from html.parser import HTMLParser

from django.test import SimpleTestCase
from django.utils import translation

from core.forms import HistoryFilterForm


class DateInputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') in {'start', 'end'}:
            self.inputs[attrs['name']] = attrs


class HistoryNativeDateTests(SimpleTestCase):
    def rendered(self, form):
        inputs = DateInputs(form.as_p()).inputs
        self.assertEqual(set(inputs), {'start', 'end'})
        self.assertEqual({row['type'] for row in inputs.values()}, {'date'})
        return inputs

    def test_typed_initial_dates_are_valid_native_values_in_every_interface(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                form = HistoryFilterForm(initial={
                    'kind': 'reports', 'start': date(2026, 11, 15),
                    'end': date(2026, 11, 30),
                })
                inputs = self.rendered(form)
                self.assertEqual(inputs['start']['value'], '2026-11-15')
                self.assertEqual(inputs['end']['value'], '2026-11-30')

    def test_iso_filter_submission_binds_the_same_dates_in_every_interface(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                form = HistoryFilterForm({
                    'kind': 'reports', 'status': '', 'start': '2026-11-15',
                    'end': '2026-11-30',
                })
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['start'], date(2026, 11, 15))
                self.assertEqual(form.cleaned_data['end'], date(2026, 11, 30))
                inputs = self.rendered(form)
                self.assertEqual(inputs['start']['value'], '2026-11-15')
                self.assertEqual(inputs['end']['value'], '2026-11-30')

    def test_range_errors_keep_both_dates_and_optional_dates_stay_optional(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                invalid = HistoryFilterForm({
                    'kind': 'reports', 'status': '', 'start': '2026-11-30',
                    'end': '2026-11-15',
                })
                self.assertFalse(invalid.is_valid())
                self.assertIn('__all__', invalid.errors)
                inputs = self.rendered(invalid)
                self.assertEqual(inputs['start']['value'], '2026-11-30')
                self.assertEqual(inputs['end']['value'], '2026-11-15')
                empty = HistoryFilterForm({'kind': 'reports', 'status': '', 'start': '', 'end': ''})
                self.assertTrue(empty.is_valid(), empty.errors)
                self.assertIsNone(empty.cleaned_data['start'])
                self.assertIsNone(empty.cleaned_data['end'])
                invalid_day = HistoryFilterForm({'kind': 'reports', 'start': '2026-02-30'})
                self.assertFalse(invalid_day.is_valid())
                self.assertIn('start', invalid_day.errors)
