"""Participation continuity, authorization and retransmission regressions."""
import uuid
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from care.models import Child, FamilyLink, Program, ProgramItem, PracticeSession, PracticeRun
from catalog.models import Activity
from . import tests as original_tests
from .models import Membership, PrivacyRequest
from .services import record_practice, resolve_privacy
from .practice_runs import start_run, stop_run, task_ticket, task_url, run_summary


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class PracticeRunTests(TestCase):
    setUpTestData = classmethod(original_tests.WorkflowTests.setUpTestData.__func__)
    payload = original_tests.WorkflowTests.payload

    def setUp(self):
        translation.activate('fr')
        self.client.force_login(self.family)
        self.second = ProgramItem.objects.create(program=self.program, activity=self.item.activity, position=2)

    def begin(self):
        run = start_run(self.family, self.program)
        return run, list(run.tasks.select_related('run', 'item'))

    def submit(self, task, **changes):
        return record_practice(self.family, task.item, self.payload(answer=task.target, **changes), task_ticket(task))

    def test_double_start_returns_same_run_and_stable_order(self):
        run, tasks = self.begin()
        self.assertEqual(start_run(self.family, self.program).pk, run.pk)
        self.assertEqual(PracticeRun.objects.count(), 1)
        self.assertEqual([t.item_id for t in tasks], [self.item.pk, self.second.pk])
        before = [task_ticket(t) for t in tasks]
        for _ in range(2):
            response = self.client.get(task_url(tasks[0]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(signing.loads(response.context['form']['ticket'].value(), salt='practice'), before[0])
        self.assertEqual([task_ticket(t) for t in run.tasks.select_related('run')], before)
        self.assertEqual(PracticeSession.objects.count(), 0)

    def test_snapshot_and_assignment_identity_are_immutable(self):
        run, tasks = self.begin()
        self.item.position = 3
        with self.assertRaises(ValidationError): self.item.save()
        tasks[0].target = 'b' if tasks[0].target == 'a' else 'a'
        with self.assertRaises(ValidationError): tasks[0].save()
        # Adding another assignment later cannot add an exercise to an existing run.
        ProgramItem.objects.create(program=self.program, activity=self.second.activity, position=3)
        self.assertEqual(run.tasks.count(), 2)

    def test_only_exact_pending_step_and_bound_ticket_are_accepted(self):
        run, tasks = self.begin()
        with self.assertRaises(ValidationError): self.submit(tasks[1])
        self.assertRedirects(self.client.get(task_url(tasks[1])), reverse('practice_run_detail', args=[run.pk]))
        for field, value in [('key', str(uuid.uuid4())), ('target', 'b' if tasks[0].target == 'a' else 'a'), ('position', 2), ('run', str(uuid.uuid4()))]:
            ticket = task_ticket(tasks[0]); ticket[field] = value
            with self.assertRaises(ValidationError): record_practice(self.family, self.item, self.payload(), ticket)
        signed = signing.dumps(task_ticket(tasks[0]), salt='practice')
        response = self.client.post(task_url(tasks[1]), self.payload(ticket=signed))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(PracticeSession.objects.count(), 0)

    def test_completion_and_final_replay_do_not_duplicate_reports(self):
        run, tasks = self.begin()
        self.submit(tasks[0]); report = self.submit(tasks[1])
        run.refresh_from_db(); self.assertEqual(run.state, 'completed'); self.assertIsNotNone(run.finished_at)
        self.assertEqual(self.submit(tasks[1]).pk, report.pk)
        self.assertEqual(PracticeSession.objects.count(), 2)
        with self.assertRaises(ValidationError): self.submit(tasks[1], comment='Different feedback')
        self.assertEqual(start_run(self.family, self.program).state, 'active')
        self.assertEqual(PracticeRun.objects.count(), 2)

    def test_http_last_response_replay_after_completion_returns_saved_report(self):
        run, tasks = self.begin(); self.submit(tasks[0])
        signed = self.client.get(task_url(tasks[1])).context['form']['ticket'].value()
        data = self.payload(answer=tasks[1].target, ticket=signed)
        first = self.client.post(task_url(tasks[1]), data)
        second = self.client.post(task_url(tasks[1]), data)
        self.assertEqual(first.status_code, 302); self.assertEqual(first.url, second.url)
        self.assertEqual(PracticeSession.objects.count(), 2)
        self.assertRedirects(self.client.get(task_url(tasks[1])), first.url)

    def test_saved_replay_after_withdrawal_does_not_write_or_advance(self):
        run, tasks = self.begin()
        report = self.submit(tasks[0])
        Activity.objects.filter(pk=self.item.activity_id).update(state='withdrawn')
        signed = signing.dumps(task_ticket(tasks[0]), salt='practice')
        response = self.client.post(task_url(tasks[0]), self.payload(answer=tasks[0].target, ticket=signed))
        self.assertRedirects(response, reverse('practice_report', args=[report.pk]))
        self.assertEqual(PracticeSession.objects.count(), 1)
        run.refresh_from_db(); self.assertEqual(run.state, 'active')

    def test_stop_during_activity_keeps_remaining_tasks_unstarted(self):
        run, tasks = self.begin()
        report = record_practice(self.family, tasks[0].item, self.payload(answer='', completion='stopped', parent_report='help'), task_ticket(tasks[0]))
        run.refresh_from_db(); self.assertEqual(run.state, 'stopped'); self.assertIsNone(report.correct)
        self.assertEqual(PracticeSession.objects.count(), 1)
        summary = run_summary(run, self.family)
        self.assertEqual(summary['reported_count'], 1); self.assertIsNone(summary['resume_url'])
        self.assertIsNone(summary['tasks'][1].saved_report)
        with self.assertRaises(ValidationError): self.submit(tasks[1])

    def test_end_without_attempt_creates_no_invented_report(self):
        run, tasks = self.begin(); stop_run(self.family, run)
        run.refresh_from_db(); ended = run.finished_at; stop_run(self.family, run); run.refresh_from_db()
        self.assertEqual(run.finished_at, ended); self.assertEqual(run.state, 'stopped')
        self.assertEqual(PracticeSession.objects.count(), 0)
        self.assertEqual(run_summary(run, self.family)['reported_count'], 0)

    def test_withdrawal_blocks_current_step_without_skipping_and_can_close(self):
        run, tasks = self.begin()
        Activity.objects.filter(pk=self.item.activity_id).update(state='withdrawn')
        response = self.client.get(reverse('practice_run_detail', args=[run.pk]))
        self.assertEqual(response.status_code, 200); self.assertIsNone(response.context['resume_url'])
        self.assertEqual(response.context['pending'].pk, tasks[0].pk); self.assertTrue(response.context['blocked_reason'])
        with self.assertRaises(ValidationError): self.submit(tasks[0])
        self.assertEqual(self.client.post(reverse('practice_run_stop', args=[run.pk])).status_code, 302)
        self.assertEqual(PracticeSession.objects.count(), 0)
        with self.assertRaises(ValidationError): start_run(self.family, self.program)

    def test_future_withdrawal_is_not_silently_skipped(self):
        source = self.item.activity
        activity = Activity.objects.create(variety=source.variety, series=uuid.uuid4(), title='Future fictional task', contrast='demo', word_a='a', word_b='b', image_a=source.image_a, image_b=source.image_b, instructions=source.instructions, rights=source.rights, population='Fictional', state='published')
        # New assignment identity, before a run is started.
        self.second.delete()
        self.second = ProgramItem.objects.create(program=self.program, activity=activity, position=2)
        run, tasks = self.begin()
        ProgramItem.objects.create(program=self.program, activity=source, position=3)
        Activity.objects.filter(pk=activity.pk).update(state='withdrawn')
        self.submit(tasks[0])
        summary = run_summary(run, self.family)
        self.assertEqual(summary['pending'].pk, tasks[1].pk); self.assertIsNone(summary['resume_url'])
        self.assertEqual(summary['reported_count'], 1); self.assertEqual(summary['task_count'], 2)
        with self.assertRaises(ValidationError): self.submit(tasks[1])

    def test_scope_revocation_blocks_history_and_even_replay(self):
        run, tasks = self.begin(); self.submit(tasks[0])
        FamilyLink.objects.filter(user=self.family, child=self.child).update(active=False)
        for name, pk in [('practice_run_detail', run.pk), ('practice_run_stop', run.pk), ('practice_run_start', self.program.pk)]:
            response = self.client.get(reverse(name, args=[pk])) if name.endswith('detail') else self.client.post(reverse(name, args=[pk]))
            self.assertEqual(response.status_code, 404)
        with self.assertRaises(ValidationError): self.submit(tasks[0])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('practice_run_detail', args=[run.pk])).status_code, 404)

    def test_clinician_can_read_but_cannot_resume_or_stop_family_run(self):
        run, tasks = self.begin(); self.submit(tasks[0]); self.client.force_login(self.pro)
        response = self.client.get(reverse('practice_run_detail', args=[run.pk]))
        self.assertEqual(response.status_code, 200); self.assertFalse(response.context['own_run']); self.assertIsNone(response.context['resume_url'])
        self.assertEqual(self.client.get(task_url(tasks[1])).status_code, 404)
        self.assertEqual(self.client.post(reverse('practice_run_stop', args=[run.pk])).status_code, 404)
        Membership.objects.create(user=self.other, organization=self.org, role='clinician')
        Child.objects.filter(pk=self.child.pk).update(responsible=self.other)
        self.assertEqual(self.client.get(reverse('practice_run_detail', args=[run.pk])).status_code, 404)

    def test_archive_or_completed_program_blocks_new_reports_keeps_summary(self):
        run, tasks = self.begin(); self.submit(tasks[0])
        for model, pk, changes in [(Child, self.child.pk, {'active':False}), (Program, self.program.pk, {'state':'completed'})]:
            model.objects.filter(pk=pk).update(**changes)
            with self.assertRaises(ValidationError): self.submit(tasks[1])
            self.assertEqual(self.client.get(reverse('practice_run_detail', args=[run.pk])).status_code, 200)
            Child.objects.filter(pk=self.child.pk).update(active=True)
        self.assertEqual(PracticeSession.objects.count(), 1)
        stop_run(self.family, run)

    def test_language_screens_export_and_retention_erasure_include_runs(self):
        run, tasks = self.begin(); self.submit(tasks[0])
        for lang in ['fr', 'en', 'ar']:
            with translation.override(lang):
                response = self.client.get(reverse('practice_run_detail', args=[run.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'dir="rtl"' if lang == 'ar' else f'lang="{lang}"')
        exported = self.client.get(reverse('export_child', args=[self.child.pk])).json()
        row = exported['programs'][0]['practice_runs'][0]
        self.assertEqual(len(row['tasks']), 2); self.assertIsNotNone(row['tasks'][0]['report_id']); self.assertIsNone(row['tasks'][1]['report_id'])
        self.org.retention_days = 0; self.org.save()
        request = PrivacyRequest.objects.create(organization=self.org, child=self.child, requester=self.family, kind='erasure')
        resolve_privacy(self.pro, request.pk, dict(decision='erase', confirmation=self.child.code, reason='Fictional erasure test'))
        self.assertFalse(PracticeRun.objects.filter(pk=run.pk).exists()); self.assertEqual(PracticeSession.objects.count(), 0)

    @override_settings(DEMO_MODE=False)
    def test_real_mode_refuses_legacy_demo_run(self):
        with self.assertRaises(ValidationError): start_run(self.family, self.program)
        self.assertEqual(PracticeRun.objects.count(), 0)

    def test_malformed_signed_ticket_cannot_crash_or_create_report(self):
        for ticket in [{}, {'user':self.family.pk, 'item':str(self.item.pk), 'key':'bad', 'target':'a'}]:
            response = self.client.post(reverse('practice', args=[self.item.pk]), self.payload(ticket=signing.dumps(ticket, salt='practice')))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(PracticeSession.objects.count(), 0)
