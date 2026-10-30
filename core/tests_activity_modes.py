"""Real free-choice and observation flows without invented closed-task scores."""
import hashlib
import json
import uuid
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from care.models import Program, ProgramItem, PracticeSession
from catalog.models import Activity
from followup.models import ClinicalGoal, ProbeExposure
from . import tests as original_tests
from .forms import PracticeForm
from .services import record_practice
from .practice_runs import start_run, task_ticket, task_url


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class ActivityModeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        original_tests.WorkflowTests.setUpTestData.__func__(cls)
        cls.mode_items = {}
        source = cls.item.activity
        for position, mode in enumerate(['free', 'observation'], 2):
            values = {field.attname: getattr(source, field.attname) for field in source._meta.concrete_fields
                      if field.name not in ['id', 'created_at', 'series', 'title', 'response_mode']}
            activity = Activity.objects.create(**values, series=uuid.uuid4(),
                                               title='Fictional ' + mode, response_mode=mode)
            cls.mode_items[mode] = ProgramItem.objects.create(
                program=cls.program, activity=activity, position=position)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.family)

    def ticket_for(self, item, target='a'):
        return {'user': self.family.pk, 'item': str(item.pk), 'key': str(uuid.uuid4()), 'target': target}

    def payload(self, **changes):
        value = {'answer': 'a', 'completion': 'completed', 'parent_report': 'easy', 'comment': ''}
        value.update(changes)
        return value

    def test_free_choices_have_no_correct_answer_and_replays_preserve_the_choice(self):
        item = self.mode_items['free']
        for answer in ['a', 'b']:
            ticket = self.ticket_for(item)
            payload = self.payload(answer=answer)
            report = record_practice(self.family, item, payload, ticket)
            self.assertEqual(report.response_mode, 'free')
            self.assertEqual(report.answer, answer)
            self.assertIsNone(report.correct)
            self.assertEqual(record_practice(self.family, item, payload, ticket).pk, report.pk)
            with self.assertRaises(ValidationError):
                record_practice(self.family, item, self.payload(answer='b' if answer == 'a' else 'a'), ticket)
        self.assertEqual(PracticeSession.objects.count(), 2)
        self.assertEqual(set(ProbeExposure.objects.values_list('status', flat=True)), {'trained'})

    def test_observation_ignores_injected_answers_and_replays_only_actual_feedback(self):
        item = self.mode_items['observation']
        ticket = self.ticket_for(item)
        payload = self.payload(answer='invented')
        report = record_practice(self.family, item, payload, ticket)
        self.assertEqual(report.response_mode, 'observation')
        self.assertEqual(report.answer, '')
        self.assertIsNone(report.correct)
        self.assertEqual(record_practice(self.family, item, self.payload(answer='b'), ticket).pk, report.pk)
        with self.assertRaises(ValidationError):
            record_practice(self.family, item, self.payload(answer='', comment='Changed feedback'), ticket)
        self.assertEqual(PracticeSession.objects.count(), 1)

    def test_matching_keeps_the_historical_digest_and_stopped_is_never_scored(self):
        for answer, expected in [('a', True), ('b', False)]:
            ticket = self.ticket_for(self.item)
            payload = self.payload(answer=answer)
            report = record_practice(self.family, self.item, payload, ticket)
            old_body = dict(payload, item=str(self.item.pk), target=ticket['target'])
            expected_digest = hashlib.sha256(json.dumps(old_body, sort_keys=True).encode()).hexdigest()
            self.assertEqual(report.payload_digest, expected_digest)
            self.assertEqual(report.response_mode, 'matching')
            self.assertEqual(report.correct, expected)
            self.assertEqual(record_practice(self.family, self.item, payload, ticket).pk, report.pk)
        for item in [self.item, *self.mode_items.values()]:
            report = record_practice(self.family, item, self.payload(completion='stopped', answer='b'), self.ticket_for(item))
            self.assertEqual(report.answer, '')
            self.assertIsNone(report.correct)

    def test_forms_require_a_real_choice_only_for_matching_and_free(self):
        for mode in ['matching', 'free']:
            form = PracticeForm(self.payload(ticket='signed', answer=''), response_mode=mode)
            self.assertFalse(form.is_valid())
            self.assertIn('answer', form.errors)
        form = PracticeForm(self.payload(ticket='signed', answer='invented'), response_mode='observation')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('answer', form.fields)
        self.assertEqual(form.cleaned_data['answer'], '')
        invalid_stop = PracticeForm(self.payload(ticket='signed', answer='', stop_reason='fatigue'), response_mode='observation')
        self.assertFalse(invalid_stop.is_valid())
        self.assertIn('stop_reason', invalid_stop.errors)

    def test_model_rejects_scores_or_answers_that_do_not_belong_to_the_mode(self):
        free = record_practice(self.family, self.mode_items['free'], self.payload(), self.ticket_for(self.mode_items['free']))
        free.correct = True
        with self.assertRaises(ValidationError):
            free.save()
        free.correct = None
        free.response_mode = 'matching'
        with self.assertRaises(ValidationError):
            free.save()
        observation = record_practice(self.family, self.mode_items['observation'], self.payload(answer=''), self.ticket_for(self.mode_items['observation']))
        observation.answer = 'a'
        with self.assertRaises(ValidationError):
            observation.save()

    def test_free_ui_never_sets_a_target_or_describes_either_choice_as_wrong(self):
        item = self.mode_items['free']
        for answer in ['a', 'b']:
            page = self.client.get(reverse('practice', args=[item.pk]))
            self.assertEqual(page.context['target'], '')
            self.assertEqual(page.context['audio'], '')
            self.assertContains(page, 'Choose a picture freely')
            self.assertContains(page, 'Both choices are welcome.')
            self.assertNotContains(page, 'class="target"')
            self.assertContains(page, 'name="answer"')
            payload = self.payload(ticket=page.context['form'].initial['ticket'], answer=answer)
            saved = self.client.post(reverse('practice', args=[item.pk]), payload)
            self.assertEqual(saved.status_code, 302)
            result = self.client.get(saved.url)
            self.assertContains(result, 'Picture selected freely')
            self.assertNotContains(result, 'A different picture selected')
            self.assertNotContains(result, 'Matching picture selected')
            report = PracticeSession.objects.latest('created_at')
            detail = self.client.get(reverse('report_detail', args=[report.pk]))
            self.assertContains(detail, 'Picture selected freely')
            self.assertNotContains(detail, 'A different picture selected')

    def test_observation_ui_records_completion_without_a_picture_question(self):
        item = self.mode_items['observation']
        page = self.client.get(reverse('practice', args=[item.pk]))
        self.assertEqual(page.context['target'], '')
        self.assertContains(page, 'data-response-mode="observation"')
        self.assertContains(page, 'Play together')
        self.assertNotContains(page, 'name="answer"')
        self.assertNotContains(page, 'class="target"')
        data = self.payload(ticket=page.context['form'].initial['ticket'], answer='invented')
        saved = self.client.post(reverse('practice', args=[item.pk]), data)
        self.assertEqual(saved.status_code, 302)
        result = self.client.get(saved.url)
        self.assertContains(result, 'Shared activity reported')
        self.assertNotContains(result, 'A different picture selected')
        report = PracticeSession.objects.get()
        self.assertEqual(report.answer, '')
        self.assertIsNone(report.correct)

    def test_summaries_history_and_export_exclude_free_observation_from_answer_denominator(self):
        for answer in ['a', 'b']:
            record_practice(self.family, self.item, self.payload(answer=answer), self.ticket_for(self.item))
        for mode in ['free', 'observation']:
            item = self.mode_items[mode]
            record_practice(self.family, item, self.payload(answer='b' if mode == 'free' else ''), self.ticket_for(item))
        record_practice(self.family, self.mode_items['free'], self.payload(completion='stopped', answer=''), self.ticket_for(self.mode_items['free']))
        response = self.client.get(reverse('program_detail', args=[self.program.pk]))
        self.assertEqual(response.context['stats'], {'attempts': 5, 'answered': 2, 'correct': 1, 'stopped': 1})
        history = self.client.get(reverse('program_history', args=[self.program.pk]))
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, self.mode_items['free'].activity.title)
        self.assertContains(history, self.mode_items['observation'].activity.title)
        export = self.client.get(reverse('export_child', args=[self.child.pk])).json()
        sessions = [s for p in export['programs'] for i in p['items'] for s in i['sessions']]
        self.assertEqual(len(sessions), 5)
        self.assertEqual(sum(s['closed_task_correct'] is not None for s in sessions), 2)
        self.assertEqual({s['response_mode'] for s in sessions}, {'matching', 'free', 'observation'})
        self.assertTrue(all(s['closed_task_correct'] is None for s in sessions if s['response_mode'] != 'matching'))

    def test_unscored_null_history_is_not_rendered_as_an_incorrect_picture(self):
        report = record_practice(self.family, self.item, self.payload(), self.ticket_for(self.item))
        PracticeSession.objects.filter(pk=report.pk).update(correct=None)
        page = self.client.get(reverse('report_detail', args=[report.pk]))
        self.assertContains(page, 'No scored answer recorded')
        self.assertNotContains(page, 'A different picture selected')

    def test_mixed_unscored_run_finishes_and_replays_without_adding_reports(self):
        program = Program.objects.create(organization=self.org, child=self.child, variety=self.program.variety,
                                         created_by=self.pro, title='Fictional mixed participation run')
        for position, mode in enumerate(['free', 'observation'], 1):
            ProgramItem.objects.create(program=program, activity=self.mode_items[mode].activity, position=position)
        run = start_run(self.family, program)
        tasks = list(run.tasks.select_related('run', 'item'))
        free_report = record_practice(self.family, tasks[0].item, self.payload(answer='b'), task_ticket(tasks[0]))
        page = self.client.get(task_url(tasks[1]))
        payload = self.payload(answer='', ticket=page.context['form'].initial['ticket'])
        first = self.client.post(task_url(tasks[1]), payload)
        second = self.client.post(task_url(tasks[1]), payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertIsNone(free_report.correct)
        run.refresh_from_db()
        self.assertEqual(run.state, 'completed')
        self.assertEqual(PracticeSession.objects.count(), 2)
        summary = self.client.get(reverse('practice_run_detail', args=[run.pk]))
        self.assertEqual(summary.context['reported_count'], 2)
        self.assertEqual(summary.context['task_count'], 2)

    def test_modes_preserve_permissions_and_probe_reservations(self):
        for item in self.mode_items.values():
            with self.assertRaises(ValidationError):
                record_practice(self.other, item, self.payload(), self.ticket_for(item))
        ClinicalGoal.objects.create(
            organization=self.org, child=self.child, author=self.pro, variety=self.program.variety,
            target_phoneme='/p/', target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'}, rationale='Fictional mode regression',
            expected_realization='Fictional target', functional_goal='Fictional goal',
            reserved_words=[self.item.activity.word_a.casefold()])
        for item in self.mode_items.values():
            with self.assertRaises(ValidationError):
                record_practice(self.family, item, self.payload(), self.ticket_for(item))
            self.assertEqual(self.client.get(reverse('practice', args=[item.pk])).status_code, 410)
        self.assertEqual(PracticeSession.objects.count(), 0)

    def fixed_program(self):
        program = Program.objects.create(organization=self.org, child=self.child, variety=self.program.variety,
                                         created_by=self.pro, title='Fictional fixed instruction run')
        items = []
        for position, target in enumerate(['a', 'b'], 1):
            source = self.item.activity
            values = {field.attname: getattr(source, field.attname) for field in source._meta.concrete_fields
                      if field.name not in ['id', 'created_at', 'series', 'requested_target']}
            activity = Activity.objects.create(**values, series=uuid.uuid4(), requested_target=target)
            items.append(ProgramItem.objects.create(program=program, activity=activity, position=position))
        return program, items

    def test_fixed_instruction_ticket_and_answer_comparison_are_consistent(self):
        _, items = self.fixed_program()
        for item in items:
            target = item.activity.requested_target
            opposite = 'b' if target == 'a' else 'a'
            with patch('core.views.secrets.choice', return_value=opposite):
                page = self.client.get(reverse('practice', args=[item.pk]))
            ticket = signing.loads(page.context['form'].initial['ticket'], salt='practice')
            self.assertEqual(ticket['target'], target)
            self.assertEqual(page.context['target'], getattr(item.activity, 'word_' + target))
            correct = record_practice(self.family, item, self.payload(answer=target), ticket)
            self.assertTrue(correct.correct)
            other_ticket = self.ticket_for(item, target=target)
            incorrect = record_practice(self.family, item, self.payload(answer=opposite), other_ticket)
            self.assertFalse(incorrect.correct)
            with self.assertRaises(ValidationError):
                record_practice(self.family, item, self.payload(answer=opposite), self.ticket_for(item, target=opposite))
            # A documentary change must not prevent a previously saved exact replay.
            Activity.objects.filter(pk=item.activity_id).update(requested_target=opposite)
            self.assertEqual(record_practice(self.family, item, self.payload(answer=target), ticket).pk, correct.pk)
        self.assertEqual(PracticeSession.objects.count(), 4)

    def test_fixed_instruction_run_targets_are_stable_and_score_the_actual_request(self):
        program, items = self.fixed_program()
        with patch('core.practice_runs.secrets.choice', return_value='b'):
            run = start_run(self.family, program)
        tasks = list(run.tasks.select_related('run', 'item'))
        self.assertEqual([t.target for t in tasks], ['a', 'b'])
        self.assertEqual(start_run(self.family, program).pk, run.pk)
        for task in tasks:
            ticket = task_ticket(task)
            report = record_practice(self.family, task.item, self.payload(answer=task.target), ticket)
            self.assertTrue(report.correct)
            self.assertEqual(record_practice(self.family, task.item, self.payload(answer=task.target), ticket).pk, report.pk)
        run.refresh_from_db()
        self.assertEqual(run.state, 'completed')
        self.assertEqual(PracticeSession.objects.count(), 2)
