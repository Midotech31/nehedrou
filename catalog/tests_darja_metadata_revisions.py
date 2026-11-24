"""Exact Darja metadata staging on fictional local records, never human approval."""
import copy
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import uuid
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings

from catalog.models import Activity, DraftWorkingCopy, EditorialGrant, Review, Variety
from catalog.services import clone_version
from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision, ReviewerCompetence


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False)
class DarjaMetadataRevisionCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Path(settings.BASE_DIR) / 'docs'
        previous = json.loads((root / 'arabic-library-v1.json').read_text(encoding='utf-8'))
        updated = json.loads((root / 'arabic-library-v2.json').read_text(encoding='utf-8'))
        cls.previous = [row for row in previous['activities'] if row['variety_code'] == 'ar-dz-pilot']
        cls.updated = {row['series']: row for row in updated['activities'] if row['variety_code'] == 'ar-dz-pilot'}
        cls.variety = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Fictional Darja fixture')
        cls.foreign_variety = Variety.objects.create(code='ar-msa-pilot', language='ar', label='Fictional other variety')
        cls.actor = User.objects.create_user('darja-revision-editor', 'darja-revision-editor@example.test')
        cls.outsider = User.objects.create_user('darja-revision-outsider', 'darja-revision-outsider@example.test')
        cls.publisher = User.objects.create_user('darja-revision-publisher', 'darja-revision-publisher@example.test')
        cls.reviewer = User.objects.create_user('darja-revision-reviewer', 'darja-revision-reviewer@example.test')
        cls.grant = EditorialGrant.objects.create(user=cls.actor, variety=cls.variety, edit=True)
        EditorialGrant.objects.create(user=cls.outsider, variety=cls.foreign_variety, edit=True)
        EditorialGrant.objects.create(user=cls.publisher, variety=cls.variety, publish=True)
        EditorialGrant.objects.create(user=cls.reviewer, variety=cls.variety, clinical_review=True)
        values = copy.deepcopy(cls.previous[0])
        values.pop('variety_code')
        cls.original = Activity.objects.create(variety=cls.variety, **values)

    def invoke(self, *arguments, actor=None):
        output = io.StringIO()
        call_command('prepare_darja_metadata_revisions', '--actor', (actor or self.actor).username,
                     *arguments, stdout=output)
        return json.loads(output.getvalue())

    def selection(self, *sources):
        return tuple(value for source in sources for value in ('--series', str(source.series)))

    def create_source(self, index=1, **changes):
        values = copy.deepcopy(self.previous[index])
        values.pop('variety_code')
        values.update(variety=self.variety, **changes)
        return Activity.objects.create(**values)

    def snapshot(self):
        return {
            'activities': list(Activity.objects.order_by('pk').values()),
            'reviews': list(Review.objects.order_by('pk').values()),
            'audits': list(AuditEvent.objects.order_by('pk').values()),
            'grants': list(EditorialGrant.objects.order_by('pk').values()),
            'working_copies': list(DraftWorkingCopy.objects.order_by('pk').values()),
        }

    def entry(self, report, source=None):
        series = str((source or self.original).series)
        return next(entry for entry in report['entries'] if entry['series'] == series)

    def apply_plan(self, plan, *sources):
        return self.invoke('--apply', '--expect-plan', plan['plan_sha256'], *self.selection(*sources))

    def test_default_preview_is_deterministic_and_never_creates_or_edits_records(self):
        before = self.snapshot()
        first = self.invoke()
        second = self.invoke()
        self.assertEqual(first, second)
        self.assertRegex(first['plan_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(first['created'], [])
        self.assertEqual(len(first['entries']), 32)
        self.assertEqual({entry['series'] for entry in first['entries']}, set(self.updated))
        self.assertEqual(self.entry(first)['status'], 'eligible')
        self.assertEqual(sum(entry['status'] == 'missing' for entry in first['entries']), 31)
        self.assertEqual(self.snapshot(), before)

    def test_preview_can_select_one_missing_source_without_manufacturing_a_baseline(self):
        series = self.previous[1]['series']
        before = self.snapshot()
        report = self.invoke('--series', series)
        self.assertEqual([(entry['series'], entry['status']) for entry in report['entries']], [(series, 'missing')])
        self.assertEqual(report['created'], [])
        with self.assertRaises(CommandError):
            self.invoke('--apply', '--expect-plan', report['plan_sha256'], '--series', series)
        self.assertEqual(self.snapshot(), before)

    def test_apply_requires_both_explicit_selection_and_the_preview_hash(self):
        preview = self.invoke(*self.selection(self.original))
        before = self.snapshot()
        for arguments in [('--apply',), ('--apply', *self.selection(self.original)),
                          ('--apply', '--expect-plan', preview['plan_sha256'])]:
            with self.subTest(arguments=arguments), self.assertRaises(CommandError):
                self.invoke(*arguments)
            self.assertEqual(self.snapshot(), before)

    def test_unknown_malformed_or_duplicate_selection_is_rejected_without_writes(self):
        before = self.snapshot()
        for arguments in [('--series', str(uuid.uuid4())), ('--series', 'not-a-uuid'),
                          self.selection(self.original, self.original)]:
            with self.subTest(arguments=arguments), self.assertRaises(CommandError):
                self.invoke(*arguments)
            self.assertEqual(self.snapshot(), before)

    def test_edit_authority_is_required_for_this_exact_variety(self):
        selection = self.selection(self.original)
        before = self.snapshot()
        for actor in (self.outsider, self.publisher, self.reviewer):
            with self.subTest(actor=actor.username), self.assertRaises(CommandError):
                self.invoke(*selection, actor=actor)
        with self.assertRaises(CommandError):
            call_command('prepare_darja_metadata_revisions', actor='nonexistent-fictional-actor', stdout=io.StringIO())
        self.assertEqual(self.snapshot(), before)

    def test_inactive_actor_or_revoked_edit_authority_cannot_apply_a_prior_preview(self):
        preview = self.invoke(*self.selection(self.original))
        self.actor.is_active = False
        self.actor.save(update_fields=['is_active'])
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_plan(preview, self.original)
        self.assertEqual(self.snapshot(), before)
        self.actor.is_active = True
        self.actor.save(update_fields=['is_active'])
        self.grant.edit = False
        self.grant.save(update_fields=['edit'])
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_plan(preview, self.original)
        self.assertEqual(self.snapshot(), before)

    def test_apply_clones_only_selected_exact_v1_and_changes_only_metadata_and_version(self):
        untouched = self.create_source()
        original_values = Activity.objects.filter(pk=self.original.pk).values().get()
        untouched_values = Activity.objects.filter(pk=untouched.pk).values().get()
        original_digest = self.original.fingerprint()
        preview = self.invoke(*self.selection(self.original))
        report = self.apply_plan(preview, self.original)
        self.assertEqual(len(report['created']), 1)
        created = report['created'][0]
        revised = Activity.objects.get(pk=created['id'])
        self.assertEqual((created['series'], created['version'], created['fingerprint']),
                         (str(self.original.series), 2, revised.fingerprint()))
        self.assertEqual((revised.state, revised.is_demo), ('draft', False))
        self.assertEqual(revised.item_metadata, self.updated[str(self.original.series)]['item_metadata'])
        self.assertNotEqual(revised.item_metadata, self.original.item_metadata)
        for field in Activity._meta.concrete_fields:
            if field.name not in ('id', 'created_at', 'version', 'item_metadata', 'search_text'):
                self.assertEqual(getattr(revised, field.attname), getattr(self.original, field.attname), field.name)
        self.assertEqual(Activity.objects.filter(pk=self.original.pk).values().get(), original_values)
        self.assertEqual(Activity.objects.filter(pk=untouched.pk).values().get(), untouched_values)
        self.original.refresh_from_db()
        self.assertEqual(self.original.fingerprint(), original_digest)
        self.assertFalse(revised.audio_a or revised.audio_b)
        self.assertFalse(revised.usable)
        self.assertEqual(Review.objects.count(), 0)
        self.assertEqual(ReviewerCompetence.objects.count(), 0)
        self.assertEqual(AvailabilityDecision.objects.count(), 0)
        audits = AuditEvent.objects.filter(actor=self.actor, object_id=str(revised.pk))
        self.assertEqual(set(audits.values_list('action', flat=True)),
                         {'catalog.version_created', 'catalog.darja_metadata_revision_prepared'})
        self.assertEqual(audits.count(), 2)
        self.assertEqual(Activity.objects.count(), 3)

    def test_refreshed_current_plan_is_idempotent_and_never_rotates_the_created_version(self):
        selection = self.selection(self.original)
        preview = self.invoke(*selection)
        self.apply_plan(preview, self.original)
        revised = Activity.objects.get(series=self.original.series, version=2)
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_plan(preview, self.original)
        self.assertEqual(self.snapshot(), before)
        refreshed = self.invoke(*selection)
        self.assertEqual(self.entry(refreshed)['status'], 'current')
        self.assertNotEqual(refreshed['plan_sha256'], preview['plan_sha256'])
        self.assertEqual(self.apply_plan(refreshed, self.original)['created'], [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(Activity.objects.get(series=self.original.series, version=2).pk, revised.pk)

    def test_plan_is_bound_to_the_exact_selection_not_a_different_series(self):
        another = self.create_source()
        one = self.invoke(*self.selection(self.original))
        both = self.invoke(*self.selection(self.original, another))
        self.assertNotEqual(one['plan_sha256'], both['plan_sha256'])
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_plan(one, self.original, another)
        self.assertEqual(self.snapshot(), before)

    def test_changed_authored_content_invalidates_old_plan_and_remains_manual(self):
        preview = self.invoke(*self.selection(self.original))
        self.original.title += ' / fictional editorial change to preserve'
        self.original.save(update_fields=['title'])
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_plan(preview, self.original)
        changed = self.invoke(*self.selection(self.original))
        self.assertEqual(self.entry(changed)['status'], 'manual')
        self.assertNotEqual(changed['plan_sha256'], preview['plan_sha256'])
        with self.assertRaises(CommandError):
            self.apply_plan(changed, self.original)
        self.assertEqual(self.snapshot(), before)

    def test_submitted_published_or_withdrawn_states_are_never_revised_automatically(self):
        preview = self.invoke(*self.selection(self.original))
        for state in ('review', 'approved', 'published', 'withdrawn'):
            # Persist a legacy state as fixture only; no approval is fabricated.
            Activity.objects.filter(pk=self.original.pk).update(state=state)
            before = self.snapshot()
            with self.subTest(state=state):
                with self.assertRaises(CommandError):
                    self.apply_plan(preview, self.original)
                changed = self.invoke(*self.selection(self.original))
                self.assertEqual(self.entry(changed)['status'], 'manual')
                with self.assertRaises(CommandError):
                    self.apply_plan(changed, self.original)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(Activity.objects.count(), 1)

    def test_open_working_copy_from_another_editor_protects_the_draft(self):
        preview = self.invoke(*self.selection(self.original))
        DraftWorkingCopy.objects.create(owner=self.outsider, activity=self.original,
                                        data={'title': 'Fictional unfinished editor input'},
                                        base_digest=self.original.fingerprint())
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_plan(preview, self.original)
        current = self.invoke(*self.selection(self.original))
        self.assertEqual(self.entry(current)['status'], 'manual')
        with self.assertRaises(CommandError):
            self.apply_plan(current, self.original)
        self.assertEqual(self.snapshot(), before)

    def test_dismissed_or_committed_working_copies_do_not_block_an_unchanged_baseline(self):
        for flags in ({'dismissed': True}, {'committed': True}):
            DraftWorkingCopy.objects.create(owner=self.actor, activity=self.original,
                                            data={'title': 'Fictional archived input'}, **flags)
        preview = self.invoke(*self.selection(self.original))
        self.assertEqual(self.entry(preview)['status'], 'eligible')
        self.assertEqual(len(self.apply_plan(preview, self.original)['created']), 1)

    def test_a_recorded_review_is_preserved_and_blocks_a_legacy_draft_revision(self):
        Activity.objects.filter(pk=self.original.pk).update(state='review')
        self.original.refresh_from_db()
        review = Review.objects.create(activity=self.original, reviewer=self.reviewer,
                                       kind='clinical', approved=False, note='Fictional changes requested')
        Activity.objects.filter(pk=self.original.pk).update(state='draft')
        before = self.snapshot()
        preview = self.invoke(*self.selection(self.original))
        self.assertEqual(self.entry(preview)['status'], 'manual')
        with self.assertRaises(CommandError):
            self.apply_plan(preview, self.original)
        self.assertEqual(self.snapshot(), before)
        review.refresh_from_db()
        self.assertFalse(review.approved)

    def test_reserved_series_with_demo_or_foreign_variety_is_never_repurposed(self):
        for changes in ({'is_demo': True}, {'variety_id': self.foreign_variety.pk}):
            Activity.objects.filter(pk=self.original.pk).update(is_demo=False, variety_id=self.variety.pk)
            Activity.objects.filter(pk=self.original.pk).update(**changes)
            before = self.snapshot()
            with self.subTest(changes=changes):
                preview = self.invoke(*self.selection(self.original))
                self.assertEqual(self.entry(preview)['status'], 'manual')
                with self.assertRaises(CommandError):
                    self.apply_plan(preview, self.original)
                self.assertEqual(self.snapshot(), before)

    def test_mixed_eligible_manual_and_missing_selection_cannot_apply_partially(self):
        another = self.create_source(title='Fictional authored work differs from source')
        absent = self.previous[2]['series']
        arguments = (*self.selection(self.original, another), '--series', absent)
        preview = self.invoke(*arguments)
        self.assertEqual({entry['status'] for entry in preview['entries']}, {'eligible', 'manual', 'missing'})
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.invoke('--apply', '--expect-plan', preview['plan_sha256'], *arguments)
        self.assertEqual(self.snapshot(), before)

    def test_failure_on_second_clone_rolls_back_first_clone_and_both_audits(self):
        another = self.create_source()
        preview = self.invoke(*self.selection(self.original, another))
        before = self.snapshot()
        calls = []

        def fail_second(actor, source):
            calls.append(source.pk)
            if len(calls) == 2:
                raise ValidationError('Fictional second clone failure')
            return clone_version(actor, source)

        with patch('catalog.management.commands.prepare_darja_metadata_revisions.clone_version', side_effect=fail_second):
            with self.assertRaises(CommandError):
                self.apply_plan(preview, self.original, another)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.snapshot(), before)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks and independent connections.')
@override_settings(DEMO_MODE=False, MFA_REQUIRED=False)
class DarjaMetadataRevisionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        root = Path(settings.BASE_DIR) / 'docs'
        previous = json.loads((root / 'arabic-library-v1.json').read_text(encoding='utf-8'))
        row = copy.deepcopy(next(row for row in previous['activities'] if row['variety_code'] == 'ar-dz-pilot'))
        row.pop('variety_code')
        self.variety = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Fictional Darja race')
        self.actor = User.objects.create_user('darja-race-editor', 'darja-race-editor@example.test')
        EditorialGrant.objects.create(user=self.actor, variety=self.variety, edit=True)
        self.original = Activity.objects.create(variety=self.variety, **row)
        output = io.StringIO()
        call_command('prepare_darja_metadata_revisions', actor=self.actor.username,
                     series=[self.original.series], stdout=output)
        self.preview = json.loads(output.getvalue())

    def worker(self, start):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
            output = io.StringIO()
            start.wait(timeout=5)
            try:
                call_command('prepare_darja_metadata_revisions', actor=self.actor.username,
                             series=[self.original.series], apply=True,
                             expect_plan=self.preview['plan_sha256'], stdout=output)
            except CommandError as error:
                return {'outcome': 'refused', 'changed_plan': 'The plan changed.' in str(error)}
            return {'outcome': 'applied', 'report': json.loads(output.getvalue())}
        finally:
            connections.close_all()

    def test_same_plan_race_creates_one_v2_and_refuses_the_stale_second_execution(self):
        baseline = Activity.objects.filter(pk=self.original.pk).values().get()
        start = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, start) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual([result['outcome'] for result in results], ['applied', 'refused'])
        refused = next(result for result in results if result['outcome'] == 'refused')
        self.assertTrue(refused['changed_plan'])
        applied = next(result['report'] for result in results if result['outcome'] == 'applied')
        self.assertEqual(len(applied['created']), 1)
        revised = Activity.objects.get(series=self.original.series, version=2)
        self.assertEqual(applied['created'][0]['id'], str(revised.pk))
        self.assertEqual((revised.state, revised.is_demo), ('draft', False))
        self.assertEqual(Activity.objects.filter(series=self.original.series).count(), 2)
        self.assertEqual(Activity.objects.filter(pk=self.original.pk).values().get(), baseline)
        audits = AuditEvent.objects.filter(actor=self.actor)
        self.assertEqual(audits.count(), 2)
        self.assertEqual(set(audits.values_list('object_id', flat=True)), {str(revised.pk)})
        self.assertEqual(set(audits.values_list('action', flat=True)),
                         {'catalog.version_created', 'catalog.darja_metadata_revision_prepared'})
        self.assertFalse(Review.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
