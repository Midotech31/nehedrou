"""Restore destination guards on disposable local/CI databases, never real data."""
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from core.backups import postgres_target_has_user_objects, restore_backup


class NamedPostgreSQLRestoreTargetTests(SimpleTestCase):
    def test_source_and_active_database_names_are_refused_before_connection_or_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / 'fresh-media'
            manifest = {'database_engine': 'postgresql', 'source_database': 'fictional_source_database'}
            for name in [manifest['source_database'], str(settings.DATABASES['default']['NAME'])]:
                with self.subTest(target=name), patch('core.backups.inspect_backup', return_value=(manifest, {})), patch('psycopg.connect') as connect:
                    with self.assertRaisesMessage(CommandError, 'distinct, existing empty PostgreSQL'):
                        restore_backup('fictional-backup.encrypted', media, postgres_database=name)
                    connect.assert_not_called()
                    self.assertFalse(media.exists())


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL catalog checks')
@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class PostgreSQLRestoreTargetTests(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        active_media = self.root / 'active-media'
        active_media.mkdir()
        media_settings = override_settings(MEDIA_ROOT=active_media)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        # The Django runner must already be on its disposable test database.
        self.assertTrue(str(connection.settings_dict['NAME']).startswith('test_'))
        self.assertIn(connection.settings_dict.get('HOST'), ('127.0.0.1', 'localhost', '::1'))
        direct_host = patch.dict(os.environ, {'POSTGRES_MIGRATION_HOST': connection.settings_dict['HOST']})
        direct_host.start()
        self.addCleanup(direct_host.stop)

    @contextmanager
    def fresh_target(self):
        import psycopg
        from psycopg import sql
        name = 'nehedrou_restore_guard_' + uuid.uuid4().hex[:16]
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        target = None
        try:
            config = connection.settings_dict
            options = {'sslmode': config['OPTIONS']['sslmode']} if config.get('OPTIONS', {}).get('sslmode') else {}
            target = psycopg.connect(host=config.get('HOST') or 'localhost',
                port=config.get('PORT') or 5432, user=config.get('USER'),
                password=config.get('PASSWORD'), dbname=name, connect_timeout=5,
                autocommit=True, **options)
            yield name, target
        finally:
            if target is not None:
                target.close()
            # Only the unique database created above is eligible for cleanup.
            assert name.startswith('nehedrou_restore_guard_')
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def check_restore(self, name, *, rejected):
        media = self.root / ('restored-media-' + uuid.uuid4().hex)
        manifest = {'database_engine': 'postgresql', 'source_database': 'fictional_other_source'}
        entries = {'database.bin': b'Fictional dump fixture; pg_restore is mocked'}
        with patch('core.backups.inspect_backup', return_value=(manifest, entries)), patch('core.backups.pg_command') as restore:
            if rejected:
                with self.assertRaisesMessage(CommandError, 'target is not empty'):
                    restore_backup('fictional-backup.encrypted', media, postgres_database=name)
                restore.assert_not_called()
                self.assertFalse(media.exists())
            else:
                result = restore_backup('fictional-backup.encrypted', media, postgres_database=name)
                self.assertTrue(result['target_was_fresh'])
                self.assertEqual(result['target_precondition'], 'no_application_objects_or_stateful_extension_relations')
                self.assertTrue(result['operator_isolation_required'])
                restore.assert_called_once()
                self.assertEqual(restore.call_args.args[:2], ('pg_restore', name))
                self.assertTrue(media.is_dir())

    def test_fresh_public_schema_is_accepted_before_mocked_restore(self):
        with self.fresh_target() as (name, target):
            self.assertFalse(postgres_target_has_user_objects(target))
            self.check_restore(name, rejected=False)

    def test_empty_nonstandard_schema_is_not_a_fresh_target(self):
        with self.fresh_target() as (name, target):
            target.execute('CREATE SCHEMA fictional_private')
            self.assertTrue(postgres_target_has_user_objects(target))
            self.check_restore(name, rejected=True)
            self.assertIsNotNone(target.execute("SELECT 1 FROM pg_namespace WHERE nspname='fictional_private'").fetchone())

    def test_table_outside_public_is_refused_without_touching_it(self):
        with self.fresh_target() as (name, target):
            target.execute('CREATE SCHEMA fictional_private')
            target.execute('CREATE TABLE fictional_private.saved_fixture(value text)')
            target.execute("INSERT INTO fictional_private.saved_fixture VALUES ('Fictional existing data')")
            self.check_restore(name, rejected=True)
            self.assertEqual(target.execute('SELECT value FROM fictional_private.saved_fixture').fetchall(), [('Fictional existing data',)])

    def test_public_functions_types_sequences_and_views_are_refused(self):
        statements = [
            "CREATE FUNCTION public.fictional_guard_function() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
            "CREATE TYPE public.fictional_status AS ENUM ('fictional')",
            'CREATE DOMAIN public.fictional_domain AS integer',
            'CREATE SEQUENCE public.fictional_sequence',
            'CREATE VIEW public.fictional_view AS SELECT 1 AS fixture',
        ]
        for statement in statements:
            with self.subTest(statement=statement), self.fresh_target() as (name, target):
                target.execute(statement)
                self.check_restore(name, rejected=True)

    def test_standard_extension_objects_and_internal_types_are_allowed_without_hiding_user_objects(self):
        with self.fresh_target() as (name, target):
            target.execute('CREATE EXTENSION hstore')
            self.assertFalse(postgres_target_has_user_objects(target))
            self.check_restore(name, rejected=False)
            target.execute("CREATE FUNCTION public.fictional_extra_function() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
            self.check_restore(name, rejected=True)

    def test_extension_owned_stateful_relations_are_not_assumed_empty(self):
        with self.fresh_target() as (name, target):
            target.execute('CREATE EXTENSION hstore')
            target.execute('CREATE TABLE public.fictional_extension_state(value text)')
            target.execute('ALTER EXTENSION hstore ADD TABLE public.fictional_extension_state')
            target.execute("INSERT INTO public.fictional_extension_state VALUES ('Fictional existing extension data')")
            self.check_restore(name, rejected=True)
            self.assertEqual(target.execute('SELECT value FROM public.fictional_extension_state').fetchall(), [('Fictional existing extension data',)])

    def test_catalog_guard_does_not_require_a_superuser_or_read_mapping_credentials(self):
        from psycopg import sql
        role = 'nehedrou_guard_reader_' + uuid.uuid4().hex[:16]
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        try:
            with self.fresh_target() as (_name, target):
                target.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
                self.assertFalse(postgres_target_has_user_objects(target))
                target.execute('RESET ROLE')
        finally:
            assert role.startswith('nehedrou_guard_reader_')
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

    def test_large_objects_and_custom_default_permissions_are_refused(self):
        for statement in ["SELECT lo_create(0)", 'ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO PUBLIC']:
            with self.subTest(statement=statement), self.fresh_target() as (name, target):
                target.execute(statement)
                self.check_restore(name, rejected=True)
