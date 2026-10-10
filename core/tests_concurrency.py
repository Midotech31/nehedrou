"""Real row-lock tests; explicitly skipped by the local SQLite test suite."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from care.models import Child, Program, PracticeSession, PracticeRun
from catalog.models import Activity
from .models import User, Organization, PrivacyRequest
from .services import create_program, record_practice, resolve_privacy
from .practice_runs import start_run, stop_run, task_ticket


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class ConcurrentQualificationTests(TransactionTestCase):
    def setUp(self):
        with patch.dict(os.environ, {'DEMO_PASSWORD':'Fictional-Demo-2026!'}):
            call_command('seed_demo',verbosity=0)
        self.pro=User.objects.get(username='praticien')
        self.family=User.objects.get(username='famille')
        self.child=Child.objects.get(code='Lina · fictif')
        self.program=self.child.programs.get()
        self.item=self.program.items.select_related('program__child','activity').get()
        self.org=self.child.organization

    def worker(self, function, started):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            started.set()
            try:
                function()
                return 'accepted'
            except ValidationError:
                return 'refused'
        finally:
            connections.close_all()

    def practice(self):
        return record_practice(self.family,self.item,{'answer':'a','completion':'completed','parent_report':'help','comment':''},{'key':str(uuid.uuid4()),'target':'a'})

    def test_practice_waits_for_archive_then_refuses(self):
        started=threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                Child.objects.filter(pk=self.child.pk).update(active=False)
                future=pool.submit(self.worker,self.practice,started)
                self.assertTrue(started.wait(3))
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=8),'refused')
        self.assertEqual(PracticeSession.objects.count(),0)

    def test_assignment_waits_for_withdrawal_then_refuses(self):
        started=threading.Event()
        def assign():
            return create_program(self.pro,self.child,dict(title='Concurrent program',variety=self.program.variety,activities=[self.item.activity],guidance='',schedule=''))
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Activity.objects.select_for_update().get(pk=self.item.activity_id)
                Activity.objects.filter(pk=self.item.activity_id).update(state='withdrawn')
                future=pool.submit(self.worker,assign,started)
                self.assertTrue(started.wait(3))
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=8),'refused')
        self.assertFalse(Program.objects.filter(title='Concurrent program').exists())

    def test_practice_waits_for_erasure_then_refuses_without_deadlock(self):
        started=threading.Event()
        self.org.retention_days=0;self.org.save()
        obj=PrivacyRequest.objects.create(organization=self.org,child=self.child,requester=self.family,kind='erasure')
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                future=pool.submit(self.worker,self.practice,started)
                self.assertTrue(started.wait(3))
                resolve_privacy(self.pro,obj.pk,dict(decision='erase',confirmation=self.child.code,reason='Fictional concurrent test'))
            self.assertEqual(future.result(timeout=8),'refused')
        self.assertEqual(PracticeSession.objects.count(),0)
        self.assertFalse(Child.objects.filter(pk=self.child.pk).exists())

    def test_parallel_starts_create_one_active_run(self):
        barrier = threading.Barrier(2)
        def begin():
            barrier.wait(timeout=5)
            return start_run(self.family, self.program)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(self.worker, begin, threading.Event()) for _ in range(2)]
            self.assertEqual([f.result(timeout=12) for f in results], ['accepted', 'accepted'])
        self.assertEqual(PracticeRun.objects.filter(state='active').count(), 1)

    def test_parallel_last_step_replay_creates_one_report(self):
        run = start_run(self.family, self.program)
        task = run.tasks.select_related('run', 'item__program__child', 'item__activity').get()
        ticket = task_ticket(task)
        barrier = threading.Barrier(2)
        def submit():
            barrier.wait(timeout=5)
            return record_practice(self.family, task.item, {'answer':task.target,'completion':'completed','parent_report':'help','comment':''}, ticket)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(self.worker, submit, threading.Event()) for _ in range(2)]
            self.assertEqual([f.result(timeout=12) for f in results], ['accepted', 'accepted'])
        self.assertEqual(PracticeSession.objects.filter(run_task=task).count(), 1)
        run.refresh_from_db(); self.assertEqual(run.state, 'completed')

    def test_response_waits_for_run_stop_then_refuses(self):
        run = start_run(self.family, self.program)
        task = run.tasks.select_related('run', 'item__program__child', 'item__activity').get()
        ticket = task_ticket(task)
        started = threading.Event()
        def submit():
            return record_practice(self.family, task.item, {'answer':task.target,'completion':'completed','parent_report':'help','comment':''}, ticket)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                future = pool.submit(self.worker, submit, started)
                self.assertTrue(started.wait(3))
                stop_run(self.family, run)
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=8), 'refused')
        self.assertEqual(PracticeSession.objects.count(), 0)
