"""Isolated checks for startup PostgreSQL routes and lock lifetime."""
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TransactionTestCase, skipUnlessDBFeature

from core.startup_database import database_routes_match, verify_migration_database


class MigrationDatabaseRouteTests(SimpleTestCase):
    def test_other_route_must_see_the_lock_and_its_release(self):
        runtime, migration = Mock(), Mock()
        milestones = Mock()
        milestones.attach_mock(runtime.rollback, 'release')
        with patch('core.startup_database.secrets.randbits', return_value=303), \
                patch('core.startup_database.try_database_lock', side_effect=[True, False, True]) as attempt:
            milestones.attach_mock(attempt, 'lock')
            self.assertTrue(database_routes_match(runtime, migration))
        self.assertEqual(milestones.mock_calls, [call.lock(runtime, 303), call.lock(migration, 303),
                                                call.release(), call.lock(migration, 303)])
        runtime.close.assert_called_once_with()
        migration.close.assert_called_once_with()

    def test_unshared_lock_and_unreleased_lock_do_not_establish_identity(self):
        for observations in ([True, True], [True, False, False], [False]):
            with self.subTest(observations=observations):
                runtime, migration = Mock(), Mock()
                with patch('core.startup_database.try_database_lock', side_effect=observations):
                    self.assertFalse(database_routes_match(runtime, migration))
                runtime.close.assert_called_once_with()
                migration.close.assert_called_once_with()

    def test_failed_connection_closes_both_transient_routes(self):
        runtime, migration = Mock(), Mock()
        migration.set_autocommit.side_effect = DatabaseError('fictional connection failure')
        with self.assertRaises(DatabaseError):
            database_routes_match(runtime, migration)
        runtime.close.assert_called_once_with()
        migration.close.assert_called_once_with()

    def test_sqlite_cannot_migrate_through_an_independent_postgresql_host(self):
        runtime = SimpleNamespace(vendor='sqlite')
        with patch('core.startup_database.connections', {'default': runtime}), \
                self.assertRaisesMessage(ImproperlyConfigured, 'requires a PostgreSQL application database'):
            verify_migration_database('alternate.fixture.invalid')

    def test_matching_host_configuration_needs_no_new_connections(self):
        runtime = Mock(vendor='postgresql', settings_dict={'HOST': 'fixture.invalid'})
        with patch('core.startup_database.connections', {'default': runtime}):
            verify_migration_database('fixture.invalid')
        runtime.copy.assert_not_called()

    def test_mismatch_and_transport_failure_are_reported_without_connection_values(self):
        runtime, migration = Mock(), Mock(settings_dict={'HOST': 'fixture.invalid'})
        default = Mock(vendor='postgresql', settings_dict={'HOST': 'fixture.invalid'})
        cases = [(None, 'did not identify the same database'),
                 (DatabaseError('fictional-secret-host'), 'Could not verify the PostgreSQL migration database')]
        for error, expected in cases:
            default.copy.side_effect = (runtime, migration)
            with self.subTest(message=expected), patch('core.startup_database.connections', {'default': default}), \
                    patch('core.startup_database.database_routes_match', side_effect=error, return_value=False), \
                    self.assertRaisesMessage(ImproperlyConfigured, expected) as observed:
                verify_migration_database('alternate.fixture.invalid')
            self.assertNotIn('fictional-secret-host', str(observed.exception))
            self.assertEqual(default.settings_dict['HOST'], 'fixture.invalid')
            self.assertEqual(migration.settings_dict['HOST'], 'alternate.fixture.invalid')


class PostgreSQLMigrationDatabaseRouteTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_real_connections_share_one_database_and_close(self):
        runtime = connection.copy(alias='startup_runtime')
        migration = connection.copy(alias='startup_migration')
        self.assertTrue(database_routes_match(runtime, migration))
        self.assertIsNone(runtime.connection)
        self.assertIsNone(migration.connection)
