"""Current clinician account checks, with fictional data and real PG row locks."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.http import Http404
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils.translation import gettext as _

from care.models import Child, Observation, Program, ProgramFeedback, ProgramItem
from core.access import CURRENT_NOTICE_VERSION
from core.models import AuditEvent, Membership, NoticeAcknowledgement, Organization, User
from core.services import create_program, publish_feedback, transfer_child
from core.test_live_integrity_writes import LiveIntegrityFixture, TEST_SETTINGS
from core.views import program_detail


class ClinicalActorFixture(LiveIntegrityFixture):
    def install(self):
        super().install()
        # The prescribing clinician is independent from content reviewers. An
        # inactive reviewer would invalidate the activity for a different reason
        # and mask the account-write regression in create_program.
        self.content_reviewer = self.pro
        self.pro = User.objects.create_user(username='independent-clinician',
                                            email='independent-clinician@example.test')
        Membership.objects.create(user=self.pro, organization=self.organization, role='clinician')
        Child.objects.filter(pk=self.child.pk).update(responsible=self.pro)
        self.child.refresh_from_db()
        self.program.child = self.child
        NoticeAcknowledgement.objects.create(user=self.pro, organization=self.organization,
            version=CURRENT_NOTICE_VERSION, language='fr')

    def prepare_operation(self, operation):
        self.operation = operation
        self.before = self.snapshot()

    @staticmethod
    def snapshot():
        return (Program.objects.count(), ProgramItem.objects.count(), ProgramFeedback.objects.count(),
                Observation.objects.count(), AuditEvent.objects.count())

    def perform_operation(self, actor):
        if self.operation == 'program':
            return create_program(actor, self.child, self.program_data('Fictional current clinician attribution'))
        if self.operation == 'feedback':
            return publish_feedback(actor, self.program, 'Fictional explicitly shared guidance')
        # Preserve the already-authenticated request identity: the regular test
        # client's backend would refresh the account before the view is entered.
        request = RequestFactory().post(reverse('program_detail', args=[self.program.pk]),
                                        {'text': 'Fictional private observation'})
        request.user = actor
        request.session = {'workspace': 'professional', 'organization': str(self.organization.pk)}
        response = program_detail(request, self.program.pk)
        if response.status_code != 302:
            self.assertEqual(response.status_code, 200)
            self.assertIn(_('Access is no longer available.').encode(), response.content)
            raise ValidationError('The actual private-observation form refused this stale request.')
        return Observation.objects.get(program=self.program, text='Fictional private observation')

    def assert_saved_operation(self, pk):
        if self.operation == 'program':
            saved = Program.objects.get(pk=pk)
            self.assertEqual(saved.created_by_id, self.pro.pk)
            self.assertEqual(saved.items.count(), 1)
            self.assertTrue(AuditEvent.objects.filter(action='program.created', object_id=str(pk)).exists())
        else:
            model = ProgramFeedback if self.operation == 'feedback' else Observation
            self.assertEqual(model.objects.get(pk=pk).author_id, self.pro.pk)
            action = 'family_feedback.published' if self.operation == 'feedback' else 'observation.created'
            self.assertEqual(AuditEvent.objects.filter(action=action, object_id=str(pk)).count(), 1)


@override_settings(**TEST_SETTINGS)
class ClinicalActorWriteTests(ClinicalActorFixture, TestCase):
    def setUp(self):
        self.install()

    def assert_deactivated_actor_is_refused(self, operation):
        self.prepare_operation(operation)
        stale_actor = User.objects.get(pk=self.pro.pk)
        User.objects.filter(pk=self.pro.pk).update(is_active=False)
        self.assertTrue(stale_actor.is_active)
        from catalog.integrity import invalidate_integrity
        invalidate_integrity()
        self.assertTrue(self.activity.usable, 'Prescriber deactivation must not mask this test by invalidating content.')
        with self.assertRaises(ValidationError):
            self.perform_operation(stale_actor)
        self.assertEqual(self.snapshot(), self.before)

    def test_deactivated_actor_cannot_create_program(self):
        self.assert_deactivated_actor_is_refused('program')

    def test_deactivated_actor_cannot_publish_family_feedback(self):
        self.assert_deactivated_actor_is_refused('feedback')

    def test_deactivated_actor_cannot_post_a_private_observation_from_an_inflight_request(self):
        self.assert_deactivated_actor_is_refused('observation')

    def test_active_persisted_actor_works_despite_stale_inactive_memory(self):
        self.pro.is_active = False
        for operation in ('program', 'feedback', 'observation'):
            with self.subTest(operation=operation):
                self.prepare_operation(operation)
                self.assert_saved_operation(self.perform_operation(self.pro).pk)

    def test_non_responsible_and_family_actors_keep_their_existing_boundaries(self):
        for operation in ('program', 'feedback', 'observation'):
            self.prepare_operation(operation)
            for actor in (self.family, self.foreign):
                with self.subTest(operation=operation, actor=actor.pk), self.assertRaises((ValidationError, Http404)):
                    self.perform_operation(actor)
            self.assertEqual(self.snapshot(), self.before)

    def test_transferred_responsibility_and_revoked_membership_still_refuse_writes(self):
        for change in ('responsibility', 'membership'):
            if change == 'responsibility':
                Child.objects.filter(pk=self.child.pk).update(responsible=self.foreign)
            else:
                Child.objects.filter(pk=self.child.pk).update(responsible=self.pro)
                Membership.objects.filter(user=self.pro, organization=self.organization).update(active=False)
            for operation in ('program', 'feedback', 'observation'):
                self.prepare_operation(operation)
                with self.subTest(change=change, operation=operation), self.assertRaises((ValidationError, Http404)):
                    self.perform_operation(self.pro)
                self.assertEqual(self.snapshot(), self.before)


@override_settings(**TEST_SETTINGS)
class ClinicalActorPostgreSQLTests(ClinicalActorFixture, TransactionTestCase):
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
        stale_actor = User.objects.get(pk=self.pro.pk)
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
                User.objects.filter(pk=self.pro.pk).update(is_active=False)
                holder = self.worker_pid()
                future = pool.submit(write_in_other_connection)
                self.assertTrue(started.wait(3))
                self.assert_blocked_by(holder, worker_pids[0], future)
                self.assertEqual(self.snapshot(), self.before)
            self.assertEqual(future.result(timeout=14), 'refused')
        self.assertTrue(stale_actor.is_active)
        self.assertFalse(User.objects.get(pk=self.pro.pk).is_active)
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
                actor = User.objects.get(pk=self.pro.pk)
                return self.perform_operation(actor).pk
            finally:
                connections.close_all()

        def deactivate_in_other_connection():
            connections.close_all()
            try:
                updater_pids.append(self.worker_pid())
                updater_started.set()
                return User.objects.filter(pk=self.pro.pk).update(is_active=False)
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
        self.assertFalse(User.objects.get(pk=self.pro.pk).is_active)
        self.assert_saved_operation(written_id)

    @skipUnlessDBFeature('has_select_for_update')
    def test_deactivation_first_refuses_program_after_waiting_for_real_account_lock(self):
        self.deactivation_wins_first('program')

    @skipUnlessDBFeature('has_select_for_update')
    def test_deactivation_first_refuses_feedback_after_waiting_for_real_account_lock(self):
        self.deactivation_wins_first('feedback')

    @skipUnlessDBFeature('has_select_for_update')
    def test_deactivation_first_refuses_private_observation_after_waiting_for_real_account_lock(self):
        self.deactivation_wins_first('observation')

    @skipUnlessDBFeature('has_select_for_update')
    def test_program_first_commits_before_waiting_deactivation(self):
        self.practice_wins_first('program')

    @skipUnlessDBFeature('has_select_for_update')
    def test_feedback_first_commits_before_waiting_deactivation(self):
        self.practice_wins_first('feedback')

    @skipUnlessDBFeature('has_select_for_update')
    def test_private_observation_first_commits_before_waiting_deactivation(self):
        self.practice_wins_first('observation')

    @skipUnlessDBFeature('has_select_for_update')
    def test_cross_practice_transfers_keep_the_account_lock_order_consistent(self):
        self.install()
        other_practice = Organization.objects.create(name='Fictional second transfer practice')
        Membership.objects.create(organization=self.organization, user=self.foreign, role='clinician')
        Membership.objects.create(organization=other_practice, user=self.pro, role='clinician')
        Membership.objects.create(organization=other_practice, user=self.foreign, role='clinician')
        other_child = Child.objects.create(organization=other_practice, responsible=self.foreign,
            code='Fictional crossed transfer', age_years=5)
        from core.services import lock_clinical_child
        first_locked, release_first, second_started = threading.Event(), threading.Event(), threading.Event()
        first_thread, first_pids, second_pids = [], [], []

        def pause_before_child(actor, child):
            if first_thread and threading.get_ident() == first_thread[0]:
                first_locked.set()
                if not release_first.wait(6):
                    raise AssertionError('The first ordered-account transfer was not released.')
            return lock_clinical_child(actor, child)

        def transfer_in_other_connection(actor_id, child, recipient_id, first):
            connections.close_all()
            try:
                pid = self.worker_pid()
                if first:
                    first_pids.append(pid)
                    first_thread.append(threading.get_ident())
                else:
                    second_pids.append(pid)
                    second_started.set()
                actor = User.objects.get(pk=actor_id)
                recipient = User.objects.get(pk=recipient_id)
                return transfer_child(actor, child, recipient).pk
            finally:
                connections.close_all()

        with patch('core.services.lock_clinical_child', side_effect=pause_before_child), \
                ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(transfer_in_other_connection, self.pro.pk, self.child, self.foreign.pk, True)
            try:
                self.assertTrue(first_locked.wait(4))
                second = pool.submit(transfer_in_other_connection, self.foreign.pk, other_child, self.pro.pk, False)
                self.assertTrue(second_started.wait(3))
                self.assert_blocked_by(first_pids[0], second_pids[0], second)
            finally:
                release_first.set()
            self.assertEqual(first.result(timeout=14), self.child.pk)
            self.assertEqual(second.result(timeout=14), other_child.pk)
        self.child.refresh_from_db()
        other_child.refresh_from_db()
        self.assertEqual(self.child.responsible_id, self.foreign.pk)
        self.assertEqual(other_child.responsible_id, self.pro.pk)
        self.assertEqual(AuditEvent.objects.filter(action='child.reassigned').count(), 2)
