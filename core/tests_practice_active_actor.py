"""Account deactivation versus care writes, using isolated fictional fixtures only."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature

from care.models import PracticeRun, PracticeRunTask, PracticeSession
from core.models import AuditEvent, User
from core.practice_runs import start_run, stop_run
from core.services import record_practice
from core.test_live_integrity_writes import LiveIntegrityFixture, TEST_SETTINGS


class ActiveActorFixture(LiveIntegrityFixture):
    def prepare_operation(self, operation):
        self.operation = operation
        self.run = start_run(self.family, self.program) if operation == 'stop' else None
        self.before = self.snapshot()

    @staticmethod
    def snapshot():
        return (PracticeSession.objects.count(), PracticeRun.objects.count(),
                PracticeRunTask.objects.count(), AuditEvent.objects.count(),
                tuple(PracticeRun.objects.order_by('pk').values_list('pk', 'state', 'finished_at')))

    def perform_operation(self, actor):
        if self.operation == 'record':
            return record_practice(actor, self.item, self.payload(),
                                   {'key': str(uuid.uuid4()), 'target': 'a'})
        if self.operation == 'start':
            return start_run(actor, self.program)
        return stop_run(actor, self.run)


@override_settings(**TEST_SETTINGS)
class InactivePracticeActorWriteTests(ActiveActorFixture, TestCase):
    def setUp(self):
        self.install()

    def assert_deactivated_actor_is_refused(self, operation):
        self.prepare_operation(operation)
        stale_actor = User.objects.get(pk=self.family.pk)
        User.objects.filter(pk=self.family.pk).update(is_active=False)
        self.assertTrue(stale_actor.is_active)
        with self.assertRaises(ValidationError):
            self.perform_operation(stale_actor)
        self.assertEqual(self.snapshot(), self.before)

    def test_deactivated_actor_cannot_record_from_an_already_authenticated_snapshot(self):
        self.assert_deactivated_actor_is_refused('record')

    def test_deactivated_actor_cannot_start_a_run(self):
        self.assert_deactivated_actor_is_refused('start')

    def test_deactivated_actor_cannot_stop_an_existing_run(self):
        self.assert_deactivated_actor_is_refused('stop')

    def test_inactive_actor_cannot_replay_a_saved_report(self):
        ticket = {'key': str(uuid.uuid4()), 'target': 'a'}
        saved = record_practice(self.family, self.item, self.payload(), ticket)
        before = self.snapshot()
        User.objects.filter(pk=self.family.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            record_practice(self.family, self.item, self.payload(), ticket)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(PracticeSession.objects.get().pk, saved.pk)

    def test_active_persisted_actor_is_used_despite_a_stale_inactive_instance(self):
        self.family.is_active = False  # Caller memory is not authorization state.
        report = record_practice(self.family, self.item, self.payload(),
                                 {'key': str(uuid.uuid4()), 'target': 'a'})
        run = start_run(self.family, self.program)
        stopped = stop_run(self.family, run)
        self.assertEqual(report.user_id, self.family.pk)
        self.assertEqual(stopped.state, 'stopped')
        self.assertEqual(PracticeSession.objects.count(), 1)


@override_settings(**TEST_SETTINGS)
class PracticeActorPostgreSQLTests(ActiveActorFixture, TransactionTestCase):
    @staticmethod
    def worker_pid():
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '8s'")
            cursor.execute("SET statement_timeout = '12s'")
            cursor.execute('SELECT pg_backend_pid()')
            return cursor.fetchone()[0]

    def assert_blocked_by(self, holder_pid, worker_pid, future):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not future.done():
            with connection.cursor() as cursor:
                cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [holder_pid, worker_pid])
                if cursor.fetchone()[0]:
                    return
            time.sleep(0.01)
        self.fail('PostgreSQL did not report the expected real User row lock.')

    def deactivation_wins_first(self, operation):
        self.install()
        self.prepare_operation(operation)
        # Authentication happened before deactivation began; do not refresh this
        # instance in the worker and thereby hide the original stale-actor bug.
        stale_actor = User.objects.get(pk=self.family.pk)
        started, worker_pids = threading.Event(), []

        def write_in_other_connection():
            connections.close_all()
            try:
                worker_pids.append(self.worker_pid())
                started.set()
                try:
                    self.perform_operation(stale_actor)
                except ValidationError:
                    return 'refused'
                return 'written'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                User.objects.filter(pk=self.family.pk).update(is_active=False)
                holder = self.worker_pid()
                future = pool.submit(write_in_other_connection)
                self.assertTrue(started.wait(3))
                self.assert_blocked_by(holder, worker_pids[0], future)
                self.assertEqual(self.snapshot(), self.before)
            self.assertEqual(future.result(timeout=14), 'refused')
        self.assertTrue(stale_actor.is_active)
        self.assertFalse(User.objects.get(pk=self.family.pk).is_active)
        self.assertEqual(self.snapshot(), self.before)

    def practice_wins_first(self, operation):
        self.install()
        self.prepare_operation(operation)
        user_locked, resume_write, updater_started = threading.Event(), threading.Event(), threading.Event()
        writer_threads, writer_pids, updater_pids = [], [], []
        original_select = User.objects.select_for_update

        def select_then_pause(*args, **kwargs):
            queryset = original_select(*args, **kwargs)
            original_get = queryset.get
            def get_then_pause(*get_args, **get_kwargs):
                actor = original_get(*get_args, **get_kwargs)
                if writer_threads and threading.get_ident() == writer_threads[0]:
                    user_locked.set()
                    if not resume_write.wait(6):
                        raise AssertionError('The care writer was not released after locking its User.')
                return actor
            queryset.get = get_then_pause
            return queryset

        def write_in_other_connection():
            connections.close_all()
            try:
                writer_pids.append(self.worker_pid())
                writer_threads.append(threading.get_ident())
                actor = User.objects.get(pk=self.family.pk)
                return self.perform_operation(actor).pk
            finally:
                connections.close_all()

        def deactivate_in_other_connection():
            connections.close_all()
            try:
                updater_pids.append(self.worker_pid())
                updater_started.set()
                return User.objects.filter(pk=self.family.pk).update(is_active=False)
            finally:
                connections.close_all()

        with patch.object(User.objects, 'select_for_update', side_effect=select_then_pause), \
                ThreadPoolExecutor(max_workers=2) as pool:
            write = pool.submit(write_in_other_connection)
            try:
                self.assertTrue(user_locked.wait(4))
                update = pool.submit(deactivate_in_other_connection)
                self.assertTrue(updater_started.wait(3))
                self.assert_blocked_by(writer_pids[0], updater_pids[0], update)
            finally:
                resume_write.set()
            written_id = write.result(timeout=14)
            self.assertEqual(update.result(timeout=14), 1)
        self.assertFalse(User.objects.get(pk=self.family.pk).is_active)
        if operation == 'record':
            self.assertEqual(PracticeSession.objects.get().pk, written_id)
            self.assertEqual(AuditEvent.objects.filter(action='practice.recorded').count(), 1)
        else:
            run = PracticeRun.objects.get(pk=written_id)
            self.assertEqual(run.state, 'stopped' if operation == 'stop' else 'active')
            self.assertEqual(AuditEvent.objects.filter(action='practice_run.' + ('stopped' if operation == 'stop' else 'started')).count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_deactivation_first_refuses_report_after_waiting_for_real_lock(self):
        self.deactivation_wins_first('record')

    @skipUnlessDBFeature('has_select_for_update')
    def test_deactivation_first_refuses_run_start_after_waiting_for_real_lock(self):
        self.deactivation_wins_first('start')

    @skipUnlessDBFeature('has_select_for_update')
    def test_deactivation_first_refuses_run_stop_after_waiting_for_real_lock(self):
        self.deactivation_wins_first('stop')

    @skipUnlessDBFeature('has_select_for_update')
    def test_report_first_commits_before_waiting_deactivation(self):
        self.practice_wins_first('record')

    @skipUnlessDBFeature('has_select_for_update')
    def test_run_start_first_commits_before_waiting_deactivation(self):
        self.practice_wins_first('start')

    @skipUnlessDBFeature('has_select_for_update')
    def test_run_stop_first_commits_before_waiting_deactivation(self):
        self.practice_wins_first('stop')
