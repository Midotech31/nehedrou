"""Native HTML date values remain ISO in translated follow-up/reviewer forms."""
from datetime import date
from html.parser import HTMLParser
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import translation

from catalog.models import Variety
from qualification.forms import CompetenceDecisionForm
from .forms import CoachingForm, GoalForm


class DateInputParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'input':
            self.inputs.append(dict(attrs))


class NativeDateInputTests(SimpleTestCase):
    def test_dates_render_as_native_iso_and_bind_without_locale_parser_changes(self):
        # Empty querysets ensure this form-control contract never reads a database.
        child = SimpleNamespace(varieties=SimpleNamespace(all=lambda:Variety.objects.none()))
        cases = [(GoalForm,'review_date',{'child':child}),
                 (CoachingForm,'next_review',{'child':child}),
                 (CompetenceDecisionForm,'checked_on',{})]
        expected = date(2026,11,15)
        for language in ('fr','en','ar'):
            with translation.override(language):
                for form_class,field,kwargs in cases:
                    with self.subTest(language=language,form=form_class.__name__):
                        form = form_class(initial={field:expected},**kwargs)
                        rendered = DateInputParser(str(form[field])).inputs
                        self.assertEqual(len(rendered),1)
                        self.assertEqual(rendered[0]['type'],'date')
                        self.assertEqual(rendered[0]['value'],'2026-11-15')
                        # Other missing fields are intentional: redisplay must keep this date.
                        bound = form_class(data={field:'2026-11-15'},**kwargs)
                        bound.is_valid()
                        self.assertNotIn(field,bound.errors)
                        self.assertEqual(bound.cleaned_data[field],expected)
                        self.assertEqual(DateInputParser(str(bound[field])).inputs[0]['value'],'2026-11-15')
