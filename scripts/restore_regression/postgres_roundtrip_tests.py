"""Actual PostgreSQL dump/encrypt/restore, current migrations, fictional records only.

The standalone runner supplies a newly initialized local cluster. This module
fails closed if run against any other database or media configuration.
"""
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import timedelta
from unittest.mock import patch

import psycopg
from psycopg import sql
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image

from core import backups


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def runner_gate(*, source_database=False):
    """Validate before Django creates/migrates its DB or resets any sequences.

    The runner starts a fresh cluster and supplies the only accepted settings.
    These checks intentionally fail on ordinary `manage.py test` invocations.
    Direct inspection is read-only and pins the numeric TCP address explicitly.
    """
    root_value = os.environ.get('NEHEDROU_RESTORE_REGRESSION_ROOT', '')
    cluster_value = os.environ.get('NEHEDROU_RESTORE_REGRESSION_CLUSTER', '')
    require(bool(root_value and cluster_value), 'STANDALONE_RUNNER_REQUIRED')
    root = Path(root_value).resolve(strict=True)
    cluster = Path(cluster_value).resolve(strict=True)
    checkout = Path(settings.BASE_DIR).resolve(strict=True)
    require(root.is_dir() and cluster.is_dir() and cluster.parent == root,
            'ISOLATED_CLUSTER_PATH_REQUIRED')
    require(not root.is_relative_to(checkout) and not cluster.is_relative_to(checkout),
            'GENERATED_FILES_MUST_STAY_OUTSIDE_CHECKOUT')
    require(connection.vendor == 'postgresql', 'POSTGRESQL_REQUIRED')
    config = connection.settings_dict
    require(config.get('HOST') == os.environ.get('POSTGRES_HOST') ==
            os.environ.get('POSTGRES_MIGRATION_HOST') == '127.0.0.1', 'LOOPBACK_ONLY')
    require(str(config.get('PORT')) == os.environ.get('POSTGRES_PORT') and
            str(config.get('PORT')).isdigit(), 'RUNNER_PORT_REQUIRED')
    user = config.get('USER', '')
    require(isinstance(user, str) and user.startswith('restore_reg_') and
            user == os.environ.get('POSTGRES_USER') and bool(config.get('PASSWORD')),
            'GENERATED_RUNNER_ROLE_REQUIRED')
    require(not any(name.startswith('PG') for name in os.environ),
            'INHERITED_LIBPQ_ENVIRONMENT_REFUSED')
    require(settings.MEDIA_STORAGE_BACKEND == 'filesystem', 'LOCAL_MEDIA_REQUIRED')
    source_name = config.get('TEST', {}).get('NAME', '')
    require(isinstance(source_name, str) and source_name.startswith('restore_reg_source_'),
            'RUNNER_TEST_DATABASE_REQUIRED')
    require(config.get('NAME') == (source_name if source_database else 'postgres'),
            'RUNNER_DATABASE_NAME_REQUIRED')
    local = dict(host='127.0.0.1', hostaddr='127.0.0.1', port=config['PORT'],
        user=user, password=config['PASSWORD'], dbname=config['NAME'],
        sslmode='disable', connect_timeout=5)
    with psycopg.connect(**local) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        require(Path(conn.execute('SHOW data_directory').fetchone()[0]).resolve() == cluster,
                'RUNNER_CLUSTER_IDENTITY_REQUIRED')
        require(conn.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1',
                'RUNNER_LOOPBACK_BIND_REQUIRED')
        require(conn.execute("SELECT current_setting('server_version_num')::int/10000").fetchone()[0] == 17,
                'POSTGRESQL_17_REQUIRED')
    return root, cluster, local


# Discovery imports this module before DiscoverRunner.setup_databases. A wrong
# invocation must stop here, before creation/migrations, rather than in setUp.
runner_gate()


def inventory(conn):
    """Same-server, normalized, order-independent row multiset fingerprints."""
    for statement in ("SET LOCAL TIME ZONE 'UTC'", "SET LOCAL DateStyle='ISO,YMD'",
            "SET LOCAL IntervalStyle='postgres'", "SET LOCAL bytea_output='hex'",
            "SET LOCAL extra_float_digits=3", "SET LOCAL row_security=off",
            "SET LOCAL search_path=pg_catalog,public", "SET LOCAL statement_timeout='30s'"):
        conn.execute(statement)
    relations = conn.execute("SELECT n.nspname,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relkind IN ('r','p','m','f') ORDER BY n.nspname COLLATE \"C\",c.relname COLLATE \"C\"").fetchall()
    if any(row[2] == 'f' for row in relations):
        raise AssertionError('Foreign tables are outside this isolated regression')
    tables = []
    for schema, name, kind in relations:
        digest = hashlib.sha256(b'nehedrou-row-multiset-v1\x00')
        count = 0
        query = sql.SQL("SELECT sha256(convert_to(to_jsonb(t)::text,'UTF8')) FROM ONLY {}.{} t ORDER BY 1").format(sql.Identifier(schema), sql.Identifier(name))
        with conn.cursor(name='rows_' + uuid.uuid4().hex) as cursor:
            cursor.execute(query)
            while rows := cursor.fetchmany(256):
                for row in rows:
                    digest.update(bytes(row[0]))
                    count += 1
        digest.update(count.to_bytes(8, 'big'))
        tables.append([schema, name, kind, count, digest.hexdigest()])
    foreign_keys = conn.execute("SELECT n.nspname,t.relname,c.conname,pg_get_constraintdef(c.oid,true),c.convalidated,c.condeferrable,c.condeferred FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE c.contype='f' AND n.nspname !~ '^pg_' AND n.nspname<>'information_schema' ORDER BY n.nspname COLLATE \"C\",t.relname COLLATE \"C\",c.conname COLLATE \"C\"").fetchall()
    sequences = []
    configs = conn.execute("SELECT n.nspname,c.relname,s.seqtypid::regtype::text,s.seqstart,s.seqincrement,s.seqmax,s.seqmin,s.seqcache,s.seqcycle FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' ORDER BY n.nspname COLLATE \"C\",c.relname COLLATE \"C\"").fetchall()
    for schema, name, *config in configs:
        state = conn.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(sql.Identifier(schema), sql.Identifier(name))).fetchone()
        sequences.append([schema, name, config, list(state)])
    return {'tables': tables, 'foreign_keys': foreign_keys, 'sequences': sequences}


class CurrentSchemaPostgreSQLRoundtripTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # TransactionTestCase._pre_setup runs before setUp. No reset is needed
        # for our generated IDs, and identity is rechecked before that lifecycle.
        runner_gate(source_database=True)
        super().setUpClass()

    def setUp(self):
        self.root, self.cluster, self.local = runner_gate(source_database=True)
        self.source_media = self.root / 'source-media'
        self.target_media = self.root / 'restored-media'
        self.source_media.mkdir()
        self.overrides = override_settings(MEDIA_ROOT=self.source_media)
        self.overrides.enable()
        self.addCleanup(self.overrides.disable)

    def fixture(self):
        from core.models import User, Organization, Membership, Entitlement, Invitation, OperatorAcceptanceObservation
        from catalog.models import Variety, MediaAsset, EditorialAccessInvitation
        from qualification.models import EvidenceDocument
        from care.models import Child, FamilyLink, Program, Observation, ProgramFeedback
        professional = User.objects.create_user('fictional-professional', 'professional@example.test', password=None)
        family = User.objects.create_user('fictional-family', 'family@example.test', password=None)
        outsider = User.objects.create_user('fictional-outsider', 'outsider@example.test', password=None)
        organization = Organization.objects.create(name='Fictional restore regression')
        Membership.objects.create(organization=organization, user=professional, role='owner')
        Entitlement.objects.create(organization=organization, expires_at=timezone.now() + timedelta(days=10))
        variety = Variety.objects.create(code='fictional-restore-ar', language='ar', label='Fictional restore variety')
        child = Child.objects.create(organization=organization, responsible=professional, code='Fictional only', age_years=5)
        child.varieties.add(variety)
        FamilyLink.objects.create(child=child, user=family)
        program = Program.objects.create(organization=organization, child=child, variety=variety,
            created_by=professional, title='Fictional restore programme', guidance='Fictional family instructions')
        Observation.objects.create(program=program, author=professional, text='FICTIONAL_PRIVATE_OBSERVATION')
        ProgramFeedback.objects.create(program=program, author=professional, text='FICTIONAL_SHARED_FEEDBACK')
        # Older application revisions issue pending invitations only. Exercise
        # manual handoff when both the model choices and method support it.
        invitation_delivery = 'manual' if ('delivery' in inspect.signature(Invitation.issue).parameters and
            'manual' in dict(Invitation._meta.get_field('delivery').choices)) else 'pending'
        editorial_delivery = 'manual' if ('delivery' in inspect.signature(EditorialAccessInvitation.issue).parameters and
            'manual' in dict(EditorialAccessInvitation._meta.get_field('delivery').choices)) else 'pending'
        invitation_kwargs = {'delivery': 'manual'} if invitation_delivery == 'manual' else {}
        editorial_kwargs = {'delivery': 'manual'} if editorial_delivery == 'manual' else {}
        invitation, _token = Invitation.issue(organization, child, 'manual-family@example.test', professional, **invitation_kwargs)
        editorial, _token = EditorialAccessInvitation.issue('manual-editor@example.test', variety,
            'clinical_review', professional, **editorial_kwargs)
        document = EvidenceDocument.objects.create(variety=variety, title='Fictional restore evidence',
            category='operations', file=ContentFile(b'Fictional evidence bytes \x00\xff', name='fictional.txt'),
            provenance='Synthetic local regression only', uploaded_by=professional)
        image = io.BytesIO()
        Image.new('RGB', (8, 8), (30, 90, 150)).save(image, format='PNG')
        asset = MediaAsset.objects.create(file=ContentFile(image.getvalue(), name='fictional.png'),
            kind='image', rights='Synthetic local test image', uploaded_by=professional)
        derivative = MediaAsset.objects.create(file=ContentFile(image.getvalue(), name='fictional-derived.png'),
            kind='image', rights='Synthetic derived fixture image', uploaded_by=professional, image_predecessor=asset)
        operator_observation = OperatorAcceptanceObservation.objects.create(
            check_code='recent_restore_and_dossier_access', scope='local_fictional', outcome='gap_found',
            observed_on=timezone.localdate(), evidence_sha256=document.sha256, recorded_by=professional)
        (self.source_media / 'unreferenced').mkdir()
        (self.source_media / 'unreferenced' / 'fictional.bin').write_bytes(b'Unreferenced fictional media\x00\xff')
        return {'professional': professional.pk, 'family': family.pk, 'outsider': outsider.pk,
            'child': str(child.pk), 'invitation': str(invitation.pk), 'editorial': str(editorial.pk),
            'document': str(document.pk), 'asset': str(asset.pk), 'derived_asset':str(derivative.pk),
            'operator_observation':str(operator_observation.pk),
            'operator_observed_on':operator_observation.observed_on.isoformat(),
            'invitation_delivery': invitation_delivery, 'editorial_delivery': editorial_delivery}

    def test_actual_current_schema_dump_encrypt_restore_and_scoped_reads(self):
        identities = self.fixture()
        archive = self.root / 'fictional.encrypted'
        target = 'restore_reg_target_' + uuid.uuid4().hex[:16]
        target_local = {**self.local, 'dbname': target}
        original_pg = backups.pg_command
        commands = []
        created_target = False
        summary = None
        try:
            # No production-style snapshot wrapper is injected into the code
            # under test. This source is new, synthetic and has no other writers.
            with psycopg.connect(**self.local) as source:
                source.execute('SET TRANSACTION READ ONLY')
                expected = inventory(source)
            def dump(name, dbname, extra):
                self.assertEqual((name, dbname), ('pg_dump', self.local['dbname']))
                commands.append(name)
                return original_pg(name, dbname, extra)
            with patch.object(backups, 'pg_command', dump):
                created = backups.create_backup(archive)
            # Independent connection/transaction: same rows and sequence states
            # after the actual, unmodified pg_dump invocation.
            with psycopg.connect(**self.local) as source:
                source.execute('SET TRANSACTION READ ONLY')
                self.assertEqual(inventory(source), expected)
            self.assertTrue(created['encrypted'])
            self.assertNotIn(b'FICTIONAL_PRIVATE_OBSERVATION', archive.read_bytes())
            manifest, entries = backups.inspect_backup(archive)
            self.assertEqual(manifest['database_engine'], 'postgresql')
            with psycopg.connect(**{**self.local, 'dbname': 'postgres'}, autocommit=True) as admin:
                admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
                created_target = True
            def restore(name, dbname, extra):
                self.assertEqual((name, dbname), ('pg_restore', target))
                commands.append(name)
                return original_pg(name, dbname, extra)
            with patch.object(backups, 'pg_command', restore):
                result = backups.restore_backup(archive, self.target_media, postgres_database=target)
            self.assertTrue(result['target_was_fresh'])
            self.assertEqual(commands, ['pg_dump', 'pg_restore'])
            with psycopg.connect(**target_local) as conn:
                conn.execute('SET TRANSACTION READ ONLY')
                actual = inventory(conn)
            self.assertEqual(expected, actual)
            media = {name[6:]: data for name, data in entries.items() if name.startswith('media/')}
            self.assertEqual(len(media), 4)
            self.assertEqual({file.relative_to(self.target_media).as_posix() for file in self.target_media.rglob('*') if file.is_file()}, set(media))
            for name, data in media.items():
                self.assertEqual((self.target_media / name).read_bytes(), data)
            child_env = dict(os.environ, POSTGRES_DB=target, NEHEDROU_MEDIA_ROOT=str(self.target_media),
                NEHEDROU_RESTORE_REGRESSION_IDENTITIES=json.dumps(identities),
                PYTHONPATH=os.pathsep.join(sys.path), PGOPTIONS='-c default_transaction_read_only=on')
            child_env.pop('NEHEDROU_BACKUP_KEY', None)
            script = Path(__file__).resolve().parent / 'restored_application_readcheck.py'
            readcheck = subprocess.run([sys.executable, str(script)], env=child_env,
                capture_output=True, text=True, timeout=90,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(readcheck.returncode, 0, 'Restored application readcheck failed; raw subprocess output is not printed.')
            checks = json.loads(readcheck.stdout)
            self.assertEqual(set(checks), {'professional_export', 'family_private_observation_excluded',
                'family_shared_feedback_preserved', 'unrelated_account_denied',
                'practice_invitation_delivery_preserved', 'editorial_invitation_delivery_preserved',
                'referenced_evidence_intact', 'referenced_image_intact',
                'operator_evidence_reference_preserved', 'illustration_predecessor_preserved'})
            self.assertTrue(all(value is True for value in checks.values()))
            with psycopg.connect(**target_local) as conn:
                conn.execute('SET TRANSACTION READ ONLY')
                self.assertEqual(inventory(conn), actual)
            from django.db.migrations.executor import MigrationExecutor
            executor = MigrationExecutor(connection)
            self.assertFalse(executor.migration_plan(executor.loader.graph.leaf_nodes()))
            migrations = list(executor.loader.graph.leaf_nodes())
            summary = {'status': 'passed', 'table_count': len(actual['tables']),
                'foreign_key_count': len(actual['foreign_keys']), 'sequence_count': len(actual['sequences']),
                'media_count': len(media), 'all_table_row_fingerprints_match': True,
                'all_foreign_key_definitions_match': True, 'all_sequence_states_match': True,
                'all_media_bytes_match': True, 'real_pg_dump_and_pg_restore': True,
                'source_is_new_quiescent_fixture_database': True, 'current_migration_leaves': migrations,
                'pg_command_arguments_unmodified': True,
                'restored_application_readchecks': checks, 'source_snapshot_unchanged': True,
                'restored_application_readcheck_read_only': True,
                'fixture_invitation_delivery': identities['invitation_delivery'],
                'fixture_editorial_delivery': identities['editorial_delivery']}
        finally:
            if created_target:
                self.assertTrue(target.startswith('restore_reg_target_'))
                with psycopg.connect(**{**self.local, 'dbname': 'postgres'}, autocommit=True) as admin:
                    admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
        # Never leave a passed receipt when target cleanup raised an error.
        self.assertIsNotNone(summary)
        summary['created_and_dropped_own_target_only'] = True
        (self.root / 'roundtrip-result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
