"""Transactional email transport contract. All addresses and credentials are fictional."""
import io
import json
import ssl
import traceback
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch
from uuid import UUID

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.test import SimpleTestCase, override_settings

from core.email_backends import (
    DisabledEmailBackend, EmailTransportError, MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES, ResendEmailBackend, resend_configuration_checks,
)


TRANSPORT_SETTINGS = dict(
    RESEND_ENABLED=True, RESEND_API_KEY='re_fictional_unit_key',
    DEFAULT_FROM_EMAIL='Nehedrou <access@fictional-mail.tld>',
    EMAIL_HTTP_CONNECT_TIMEOUT=3, EMAIL_HTTP_READ_TIMEOUT=7,
)
SAFE_ERROR = 'Transactional email is unavailable.'
SENSITIVE = ('re_fictional_unit_key', 'reader@recipient.test',
             'https://fixture.invalid/reset/secret-token', 'provider-private-body')


@override_settings(**TRANSPORT_SETTINGS)
class ResendEmailBackendTests(SimpleTestCase):
    def setUp(self):
        # Even an accidentally unmocked connection must never leave this process.
        network = patch('socket.create_connection', side_effect=AssertionError('Network is prohibited in transport tests.'))
        network.start()
        self.addCleanup(network.stop)
        http = patch('core.email_backends.http.client.HTTPSConnection')
        self.https = http.start()
        self.addCleanup(http.stop)
        self.connection = self.https.return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.read.return_value = b'{"id":"email_fixture_123"}'

    def message(self, **kwargs):
        values = dict(subject='Accès آمن', body='Bonjour\nhttps://fixture.invalid/reset/secret-token',
                      from_email='ACCESS@FICTIONAL-MAIL.TLD', to=['reader@recipient.test'])
        values.update(kwargs)
        return EmailMessage(**values)

    def assert_rejected_locally(self, message=None):
        self.https.reset_mock()
        with self.assertRaisesMessage(EmailTransportError, SAFE_ERROR):
            ResendEmailBackend().send_messages([message if message is not None else self.message()])
        self.https.assert_not_called()
        self.assertEqual(ResendEmailBackend(fail_silently=True).send_messages(
            [message if message is not None else self.message()]), 0)
        self.https.assert_not_called()

    def test_fixed_https_tls_timeouts_payload_and_cleanup(self):
        message = self.message()
        self.assertEqual(ResendEmailBackend().send_messages([message]), 1)
        args, kwargs = self.https.call_args
        self.assertEqual(args, ('api.resend.com', 443))
        self.assertEqual(kwargs['timeout'], 3.0)
        self.assertIsInstance(kwargs['context'], ssl.SSLContext)
        self.assertTrue(kwargs['context'].check_hostname)
        self.assertEqual(kwargs['context'].verify_mode, ssl.CERT_REQUIRED)
        self.connection.set_debuglevel.assert_called_once_with(0)
        self.connection.connect.assert_called_once_with()
        self.connection.sock.settimeout.assert_called_once_with(7.0)
        args, kwargs = self.connection.request.call_args
        self.assertEqual(args, ('POST', '/emails'))
        self.assertIsInstance(kwargs['body'], bytes)
        self.assertEqual(json.loads(kwargs['body']), {
            'from': TRANSPORT_SETTINGS['DEFAULT_FROM_EMAIL'], 'to': message.to,
            'subject': message.subject, 'text': message.body,
        })
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer re_fictional_unit_key')
        self.assertEqual(kwargs['headers']['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(kwargs['headers']['Accept'], 'application/json')
        self.assertEqual(UUID(kwargs['headers']['Idempotency-Key']).version, 4)
        self.response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
        self.response.close.assert_called_once_with()
        self.connection.close.assert_called_once_with()

    def test_optional_html_alternative_and_html_message_are_preserved(self):
        message = EmailMultiAlternatives('Sujet', 'Texte', TRANSPORT_SETTINGS['DEFAULT_FROM_EMAIL'], ['reader@recipient.test'])
        message.attach_alternative('<p lang="ar">مرحبا</p>', 'text/html')
        self.assertEqual(ResendEmailBackend().send_messages([message]), 1)
        payload = json.loads(self.connection.request.call_args.kwargs['body'])
        self.assertEqual(payload['text'], 'Texte')
        self.assertEqual(payload['html'], '<p lang="ar">مرحبا</p>')
        message = self.message()
        message.content_subtype = 'html'
        message.body = '<p>Bonjour</p>'
        self.assertEqual(ResendEmailBackend().send_messages([message]), 1)
        payload = json.loads(self.connection.request.call_args.kwargs['body'])
        self.assertEqual(payload['html'], message.body)
        self.assertNotIn('text', payload)

    def test_every_intentional_send_gets_a_new_idempotency_key(self):
        message = self.message()
        self.assertEqual(ResendEmailBackend().send_messages([message, message]), 2)
        keys = [call.kwargs['headers']['Idempotency-Key'] for call in self.connection.request.call_args_list]
        self.assertEqual(len(set(keys)), 2)
        self.assertTrue(all(UUID(key).version == 4 for key in keys))
        self.assertEqual(self.https.call_count, 2)

    def test_empty_batches_need_no_configuration_or_connection(self):
        with override_settings(RESEND_ENABLED=False, RESEND_API_KEY=''):
            for messages in (None, [], (), iter(())):
                with self.subTest(messages=type(messages).__name__):
                    self.assertEqual(ResendEmailBackend().send_messages(messages), 0)
        self.https.assert_not_called()

    def test_opt_in_and_key_are_required_before_network(self):
        for value in (False, None, 1, 'true'):
            with self.subTest(enabled=value), override_settings(RESEND_ENABLED=value):
                self.assert_rejected_locally()
        for key in ('', None, ' ', 'key with space', 'key\r\nsecret', 'clé', 'x' * 513):
            with self.subTest(key_length=len(key) if isinstance(key, str) else None), override_settings(RESEND_API_KEY=key):
                self.assert_rejected_locally()

    def test_sender_must_be_one_valid_non_reserved_configured_mailbox(self):
        for sender in ('', 'invalid', 'a@fictional-mail.tld,b@fictional-mail.tld',
                       'Group: a@fictional-mail.tld;', 'access@fictional-mail.tld\r\nBcc: hidden@recipient.test',
                       'a@example.com', 'a@mail.example.org', 'a@service.invalid',
                       'a@service.test', 'a@service.localhost', 'a@localhost'):
            with self.subTest(sender=sender), override_settings(DEFAULT_FROM_EMAIL=sender):
                self.assert_rejected_locally()
        for sender in ('other@fictional-mail.tld', 'access@fictional-mail.tld\n',
                       'Group: access@fictional-mail.tld;'):
            with self.subTest(caller_sender=sender):
                self.assert_rejected_locally(self.message(from_email=sender))

    def test_sender_display_name_cannot_override_the_configured_identity(self):
        message = self.message(from_email='Different name <access@fictional-mail.tld>')
        self.assertEqual(ResendEmailBackend().send_messages([message]), 1)
        self.assertEqual(json.loads(self.connection.request.call_args.kwargs['body'])['from'], TRANSPORT_SETTINGS['DEFAULT_FROM_EMAIL'])

    def test_invalid_recipients_and_subject_headers_are_rejected_before_network(self):
        for recipients in ([], ['invalid'], ['a@recipient.test\r\nBcc: b@recipient.test'],
                           ['Group: a@recipient.test;'], ['a@recipient.test,b@recipient.test'],
                           ['a@recipient.test'] * 51, [None]):
            with self.subTest(recipient_count=len(recipients)):
                self.assert_rejected_locally(self.message(to=recipients))
        for subject in ('Hello\r\nBcc: b@recipient.test', 'Hello\n', 'Hello\x00'):
            with self.subTest(subject=repr(subject)):
                self.assert_rejected_locally(self.message(subject=subject))

    def test_recipient_display_name_and_international_domain_are_preserved_safely(self):
        self.assertEqual(ResendEmailBackend().send_messages([
            self.message(to=['Parent <reader@exämple.tld>'])]), 1)
        payload = json.loads(self.connection.request.call_args.kwargs['body'])
        self.assertEqual(payload['to'], ['Parent <reader@xn--exmple-cua.tld>'])

    def test_unsupported_headers_recipients_and_attachments_fail_explicitly(self):
        for field, value in (('cc', ['a@recipient.test']), ('bcc', ['a@recipient.test']),
                             ('reply_to', ['a@recipient.test']), ('extra_headers', {'X-Private': 'value'}),
                             ('attachments', [('notice.txt', 'private attachment', 'text/plain')])):
            with self.subTest(field=field):
                message = self.message()
                setattr(message, field, value)
                self.assert_rejected_locally(message)
        self.assert_rejected_locally(object())

    def test_unsupported_mime_and_encoding_are_not_silently_dropped(self):
        for field, value in (('encoding', 'latin-1'), ('content_subtype', 'calendar'),
                             ('mixed_subtype', 'related'), ('alternative_subtype', 'related')):
            with self.subTest(field=field):
                message = self.message()
                setattr(message, field, value)
                self.assert_rejected_locally(message)
        for alternatives in ([('calendar', 'text/calendar')], [('a', 'text/html'), ('b', 'text/html')]):
            message = EmailMultiAlternatives('Subject', 'Body', TRANSPORT_SETTINGS['DEFAULT_FROM_EMAIL'], ['reader@recipient.test'])
            message.alternatives = alternatives
            self.assert_rejected_locally(message)
        self.assert_rejected_locally(self.message(body='x' * (MAX_REQUEST_BYTES + 1)))

    def test_timeout_configuration_is_finite_bounded_and_boolean_free(self):
        for field, maximum in (('EMAIL_HTTP_CONNECT_TIMEOUT', 15), ('EMAIL_HTTP_READ_TIMEOUT', 30)):
            for value in (0, .5, maximum + 1, float('inf'), float('nan'), True, '5', None, 10 ** 1000):
                with self.subTest(field=field, value=repr(value)[:30]), override_settings(**{field: value}):
                    checks = resend_configuration_checks()
                    self.assertTrue(all(isinstance(check, bool) for check in checks.values()))
                    self.assert_rejected_locally()
            for value in (1, maximum):
                with self.subTest(field=field, bound=value), override_settings(**{field: value}):
                    self.assertTrue(all(resend_configuration_checks().values()))

    def test_configuration_report_contains_only_local_booleans(self):
        checks = resend_configuration_checks()
        self.assertEqual(set(checks), {'enabled', 'api_key_present', 'sender_address',
            'sender_not_reserved', 'connect_timeout_bounded', 'read_timeout_bounded'})
        self.assertTrue(all(value is True for value in checks.values()))
        self.https.assert_not_called()
        for value in SENSITIVE:
            self.assertNotIn(value, json.dumps(checks))

    def test_non_success_statuses_never_read_body_follow_redirects_or_retry(self):
        for status in (301, 302, 307, 308, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.https.reset_mock()
                self.response.status = status
                with self.assertRaisesMessage(EmailTransportError, SAFE_ERROR):
                    ResendEmailBackend().send_messages([self.message()])
                self.https.assert_called_once()
                self.connection.request.assert_called_once()
                self.response.read.assert_not_called()
                self.response.close.assert_called_once()
                self.connection.close.assert_called_once()

    def test_provider_response_requires_bounded_json_object_and_valid_opaque_id(self):
        invalid = [b'provider-private-body', b'\xff', b'x' * (MAX_RESPONSE_BYTES + 1),
                   'not bytes', b'[]', b'{}', b'{"id":null}', b'{"id":12}', b'{"id":""}',
                   b'{"id":"contains space"}', b'{"id":"control\\n"}', b'{"id":"bad/id"}',
                   json.dumps({'id': 'x' * 129}).encode()]
        for response in invalid:
            with self.subTest(response_type=type(response).__name__, length=len(response)):
                self.response.read.return_value = response
                with self.assertRaisesMessage(EmailTransportError, SAFE_ERROR):
                    ResendEmailBackend().send_messages([self.message()])
        for identifier in ('opaque_Provider-ID123', 'x' * 128, 'a16a2b9b-1d45-48c6-91ec-cd61ce64a613'):
            with self.subTest(identifier=identifier):
                self.response.read.return_value = json.dumps({'id': identifier}).encode()
                self.assertEqual(ResendEmailBackend().send_messages([self.message()]), 1)
        self.response.read.assert_called_with(MAX_RESPONSE_BYTES + 1)

    def test_each_transport_failure_is_generic_closed_and_silent_if_requested(self):
        for stage in ('constructor', 'connect', 'settimeout', 'request', 'getresponse', 'read'):
            with self.subTest(stage=stage):
                method = {'constructor': self.https, 'connect': self.connection.connect,
                    'settimeout': self.connection.sock.settimeout, 'request': self.connection.request,
                    'getresponse': self.connection.getresponse, 'read': self.response.read}[stage]
                method.side_effect = OSError(' '.join(SENSITIVE))
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    try:
                        ResendEmailBackend().send_messages([self.message()])
                    except EmailTransportError as error:
                        self.assertIsInstance(error, OSError)
                        self.assertEqual(str(error), SAFE_ERROR)
                        rendered = traceback.format_exc()
                    else:
                        self.fail('The failure must not be reported as accepted.')
                    self.assertEqual(ResendEmailBackend(fail_silently=True).send_messages([self.message()]), 0)
                for value in SENSITIVE:
                    self.assertNotIn(value, rendered)
                    self.assertNotIn(value, output.getvalue() + errors.getvalue())
                self.assertEqual(output.getvalue() + errors.getvalue(), '')
                method.side_effect = None

    def test_missing_socket_is_failure_before_request(self):
        self.connection.sock = None
        with self.assertRaisesMessage(EmailTransportError, SAFE_ERROR):
            ResendEmailBackend().send_messages([self.message()])
        self.connection.request.assert_not_called()
        self.connection.close.assert_called_once()

    def test_fail_silently_counts_only_individually_accepted_messages(self):
        responses = []
        for status in (200, 429, 202):
            response = Mock(status=status)
            response.read.return_value = b'{"id":"fixture_success"}'
            responses.append(response)
        self.connection.getresponse.side_effect = responses
        self.assertEqual(ResendEmailBackend(fail_silently=True).send_messages([
            self.message(), self.message(), self.message()]), 2)
        self.assertEqual(self.https.call_count, 3)
        for response in responses:
            response.close.assert_called_once()
        responses[1].read.assert_not_called()

    def test_cleanup_failure_does_not_undo_confirmed_provider_acceptance(self):
        self.response.close.side_effect = OSError('provider-private-body')
        self.connection.close.side_effect = OSError('provider-private-body')
        self.assertEqual(ResendEmailBackend().send_messages([self.message()]), 1)


class DisabledEmailBackendTests(SimpleTestCase):
    def test_empty_batches_are_zero_without_output_or_transport(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch('core.email_backends.http.client.HTTPSConnection') as https, redirect_stdout(output), redirect_stderr(errors):
            for messages in (None, [], (), iter(())):
                self.assertEqual(DisabledEmailBackend().send_messages(messages), 0)
        https.assert_not_called()
        self.assertEqual(output.getvalue() + errors.getvalue(), '')

    def test_nonempty_batch_fails_closed_without_printing_messages(self):
        message = EmailMessage('Access', 'https://fixture.invalid/reset/secret-token',
                               'access@fictional-mail.tld', ['reader@recipient.test'])
        output, errors = io.StringIO(), io.StringIO()
        with patch('core.email_backends.http.client.HTTPSConnection') as https, redirect_stdout(output), redirect_stderr(errors):
            with self.assertRaisesMessage(EmailTransportError, SAFE_ERROR):
                DisabledEmailBackend().send_messages([message])
            self.assertEqual(DisabledEmailBackend(fail_silently=True).send_messages(iter([message])), 0)
        https.assert_not_called()
        self.assertEqual(output.getvalue() + errors.getvalue(), '')