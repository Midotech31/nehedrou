"""Permission, plan, immutability and scoring regressions for the product audit."""
from datetime import date, timedelta
from unittest.mock import patch
import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from care.models import FamilyLink, PracticeSession, Program, ProgramItem
from catalog.models import Activity
from . import tests as original_tests
from .forms import ProgramForm
from .planning import practice_dates, validate_plan, activity_overview
from .services import create_program, record_practice

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class ProductCompletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        original_tests.WorkflowTests.setUpTestData.__func__(cls)
        source = cls.item.activity
        fields = {f.attname: getattr(source, f.attname) for f in source._meta.concrete_fields if f.name not in ['id','created_at','series','title']}
        cls.selectable = Activity.objects.create(**fields, series=uuid.uuid4(), title='Fictional selectable activity')

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.pro)
        self.today = timezone.localdate()

    def plan(self):
        self.program.practice_start = self.today
        self.program.practice_end = self.today + timedelta(days=35)
        self.program.practice_days = list(range(7))
        self.program.practice_minutes = 5
        self.program.save()

    def form_data(self):
        return dict(title='Fictional planned practice', goal='Fictional goal', variety=str(self.program.variety_id), activities=[str(self.selectable.pk)],
                    activity_order=str(self.selectable.pk), guidance='Fictional guidance', schedule='Agreed with a fictional family',
                    practice_start=self.today.isoformat(), practice_end=(self.today+timedelta(days=7)).isoformat(),
                    practice_days=[str(day) for day in range(7)], practice_minutes='5', action='assign')

    def ticket(self):
        return {'user': self.family.pk, 'item': str(self.item.pk), 'key': str(uuid.uuid4()), 'target':'a'}

    def payload(self):
        return {'answer':'a', 'completion':'completed', 'parent_report':'easy', 'comment':'Fictional report'}

    def test_written_guidance_remains_compatible_with_existing_programs(self):
        self.assertEqual(practice_dates(self.program), [])
        values = self.form_data()
        for key in list(values):
            if key.startswith('practice_'):
                values.pop(key)
        form = ProgramForm(values, child=self.child)
        self.assertTrue(form.is_valid(), form.errors)
        program = create_program(self.pro, self.child, form.cleaned_data)
        self.assertEqual(program.practice_days, [])
        self.assertIsNone(program.practice_start)
        self.assertEqual(program.schedule, values['schedule'])

    def test_form_saves_explicit_dates_and_days_without_changing_original(self):
        response = self.client.post(reverse('program_create', args=[self.child.pk]), self.form_data())
        self.assertEqual(response.status_code, 302)
        created = Program.objects.get(title='Fictional planned practice')
        self.assertEqual(created.practice_days, list(range(7)))
        self.assertEqual(created.practice_start, self.today)
        self.assertEqual(created.practice_minutes, 5)
        self.program.refresh_from_db()
        self.assertIsNone(self.program.practice_start)

    def test_invalid_partial_and_reversed_plans_are_rejected(self):
        for updates, key in [({'practice_start': ''}, 'practice_start'), ({'practice_end': ''}, 'practice_end'),
                             ({'practice_days': []}, 'practice_days'), ({'practice_minutes':'0'}, 'practice_minutes'),
                             ({'practice_end':(self.today-timedelta(days=1)).isoformat()}, 'practice_end')]:
            form = ProgramForm(dict(self.form_data(), **updates), child=self.child)
            self.assertFalse(form.is_valid())
            self.assertIn(key, form.errors)

    def test_model_rejects_duplicate_or_invalid_weekdays(self):
        for days in [[0,0], [True], ['0'], [7], {}, None]:
            with self.assertRaises(ValidationError):
                validate_plan(self.today, self.today, days, None)

    def test_plan_requires_an_actual_day_inside_the_period(self):
        with self.assertRaises(ValidationError):
            validate_plan(date(2026,10,12), date(2026,10,12), [6], None)

    def test_dates_respect_both_bounds_weekdays_and_export_horizon(self):
        self.plan()
        self.assertEqual(len(practice_dates(self.program)), 28)
        self.program.practice_days = [self.today.weekday()]
        self.assertEqual(practice_dates(self.program), [self.today+timedelta(days=i) for i in [0,7,14,21]])
        self.program.practice_start = self.today+timedelta(days=14)
        self.program.practice_end = self.today+timedelta(days=15)
        self.assertEqual(practice_dates(self.program), [self.today+timedelta(days=14)])

    def test_closed_archived_expired_and_far_future_plans_have_no_current_events(self):
        self.plan()
        for changes in [dict(state='completed'), dict(practice_end=self.today-timedelta(days=1)), dict(practice_start=self.today+timedelta(days=50))]:
            self.program.refresh_from_db()
            for key,value in changes.items():
                setattr(self.program,key,value)
            self.assertEqual(practice_dates(self.program), [])
        self.program.refresh_from_db()
        self.program.child.active = False
        self.assertEqual(practice_dates(self.program), [])

    def test_calendar_requires_real_access_and_never_contains_private_data(self):
        self.plan()
        url = reverse('program_calendar', args=[self.program.pk])
        for user in [self.pro, self.family]:
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            body = response.content.decode()
            self.assertEqual(body.count('BEGIN:VEVENT'), 28)
            self.assertIn('DTSTART;VALUE=DATE:', body)
            self.assertNotIn('VALARM', body)
            for private in [self.child.code, self.program.title, str(self.program.pk), self.program.guidance, self.pro.username]:
                if private:
                    self.assertNotIn(private, body)
            self.assertNotIn('\n', body.replace('\r\n',''))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_revoked_family_and_closed_program_cannot_download_calendar(self):
        self.plan()
        url = reverse('program_calendar', args=[self.program.pk])
        self.client.force_login(self.family)
        FamilyLink.objects.filter(user=self.family, child=self.child).update(active=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.pro)
        self.program.state = 'completed'
        self.program.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_calendar_download_cannot_mutate_the_plan(self):
        self.plan()
        self.assertEqual(self.client.post(reverse('program_calendar', args=[self.program.pk]), {}).status_code, 405)
        self.program.refresh_from_db()
        self.assertEqual(self.program.practice_minutes, 5)

    def test_adjustment_copies_plan_and_preserves_closed_program_history(self):
        self.plan()
        url = reverse('program_replace', args=[self.program.pk])
        initial = self.client.get(url)
        self.assertEqual(initial.context['form'].initial['practice_days'], list(range(7)))
        response = self.client.post(url, self.form_data())
        self.assertEqual(response.status_code, 302)
        self.program.refresh_from_db()
        self.assertEqual(self.program.state, 'completed')
        self.assertEqual(self.program.practice_start, self.today)
        self.assertEqual(Program.objects.get(title='Fictional planned practice').practice_minutes, 5)

    def test_summary_does_not_turn_free_choices_and_stops_into_correctness(self):
        mode_items = {'matching':self.item}
        source = self.selectable
        fields = {f.attname: getattr(source, f.attname) for f in source._meta.concrete_fields if f.name not in ['id','created_at','series','title','response_mode']}
        for position,mode in enumerate(['free','observation'],2):
            activity = Activity.objects.create(**fields, series=uuid.uuid4(), title='Fictional '+mode, response_mode=mode)
            mode_items[mode] = ProgramItem.objects.create(program=self.program, activity=activity, position=position)
        for mode, completion, answer, parent in [('matching','completed','a','easy'), ('matching','stopped','','difficult'), ('free','completed','b','help'), ('observation','completed','','easy')]:
            PracticeSession.objects.create(organization=self.org, item=mode_items[mode], user=self.family,
                reporter_role='caregiver', idempotency_key=uuid.uuid4(), payload_digest='fictional', target='a', answer=answer,
                response_mode=mode, completion=completion, correct=True if mode=='matching' and completion=='completed' else None, parent_report=parent)
        rows = activity_overview(list(mode_items.values()), PracticeSession.objects.filter(item__program=self.program))
        self.assertEqual(tuple(sum(row[key] for row in rows) for key in ['reports','completed','stopped','help','answered','correct']), (4,3,1,2,1,1))
        self.assertTrue(all(row['answered']==0 and row['correct']==0 for row in rows if row['item'].activity.response_mode!='matching'))

    def test_reserved_reports_are_excluded_from_family_summary(self):
        record_practice(self.family, self.item, self.payload(), self.ticket())
        self.client.force_login(self.family)
        with patch('core.views.reserved_activity_ids', return_value={self.item.activity_id}):
            response = self.client.get(reverse('program_detail', args=[self.program.pk]))
        self.assertEqual(response.context['stats']['attempts'], 0)
        self.assertEqual(response.context['activity_summary'], [])

    def test_dashboard_card_counts_also_exclude_reserved_reports(self):
        record_practice(self.family, self.item, self.payload(), self.ticket())
        self.client.force_login(self.family)
        with patch('core.views.reserved_activity_ids', return_value={self.item.activity_id}), patch('core.views.family_catalog_exclusions', return_value={self.item.activity_id}):
            response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['week_total'], 0)
        card = next(p for p in response.context['programs'] if p.pk == self.program.pk)
        self.assertEqual(card.activity_count, 0)
        self.assertEqual(card.report_count, 0)

    def test_builder_filters_guides_language_and_plan_render_in_all_languages(self):
        self.plan()
        for language in ['fr','en','ar']:
            with translation.override(language):
                builder = self.client.get(reverse('program_create', args=[self.child.pk]))
                self.assertContains(builder, 'data-builder-filter="kind"')
                self.assertContains(builder, 'data-builder-filter="theme"')
                self.assertContains(builder, 'data-builder-filter="mode"')
                self.assertContains(builder, 'data-search=')
                self.assertContains(builder, 'class="builder-guide"')
                detail = self.client.get(reverse('program_detail', args=[self.program.pk]))
                self.assertContains(detail, 'class="card practice-plan"')
                self.assertContains(detail, 'class="card activity-overview"')
                self.assertContains(detail, 'class="instruction-language"')
                self.assertNotIn('Nehedrou · Nehedrou', detail.content.decode())

    def test_export_and_print_keep_the_explicit_plan(self):
        self.plan()
        exported = self.client.get(reverse('export_child', args=[self.child.pk])).json()
        row = next(p for p in exported['programs'] if p['id']==str(self.program.pk))
        self.assertEqual(row['practice_plan']['practice_start'], self.today.isoformat())
        self.assertEqual(row['practice_plan']['practice_days'], list(range(7)))
        self.assertContains(self.client.get(reverse('print_program', args=[self.program.pk])), 'class="card practice-plan"')
