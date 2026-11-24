"""Normal invitation and forced MFA journeys using fictitious practices/accounts."""
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.access import CURRENT_NOTICE_VERSION, PENDING_NOTICE_INVITATION_DIGEST
from core.invitation_mfa import SESSION_KEY, TTL_SECONDS
from core.models import Entitlement, Membership, NoticeAcknowledgement, Organization, RecoveryCode, User
from core.services import issue_manual_practice_invitation
from core.testing import practice_form_data


PASSWORD = 'Garage-Bright-95-Fixture!'


def otp(device):
    return str(TOTP(device.bin_key, device.step, device.t0, device.digits).token()).zfill(device.digits)


@override_settings(DEMO_MODE=False, MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PracticeInvitationMFAContinuationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.original = Organization.objects.create(name='Fictional previous practice')
        cls.target = Organization.objects.create(name='Fictional inviting practice')
        cls.owner = User.objects.create_user('mfa-fixture-target-owner', 'owner@example.test')
        Membership.objects.create(user=cls.owner, role='owner', organization=cls.target)
        NoticeAcknowledgement.objects.create(user=cls.owner, organization=cls.target,
                                              version=CURRENT_NOTICE_VERSION, language='en')
        Entitlement.objects.create(organization=cls.target, expires_at=timezone.now() + timedelta(days=14),
                                   practitioner_quota=10, child_quota=10)

    def existing_clinician(self, suffix, confirmed=True):
        user = User.objects.create_user('mfa-returning-' + suffix, suffix + '@example.test', password=PASSWORD)
        Membership.objects.create(user=user, role='clinician', organization=self.original)
        if confirmed:
            return user, TOTPDevice.objects.create(user=user, name='synthetic', confirmed=True)
        return user, None

    def invite(self, email, language):
        invitation, raw = issue_manual_practice_invitation(
            self.owner, self.target, None, email, 'clinician', uuid4(),
        )
        return invitation, raw, f'/{language}/invite/{raw}/'

    def login(self, client, user, link, language):
        login = f'/{language}/login/?next={link}'
        self.assertContains(client.get(link), f'href="{login}"')
        response = client.post(login, {'username': user.username, 'password': PASSWORD, 'next': link})
        self.assertRedirects(response, link, fetch_redirect_response=False)
        return client.get(link)

    def marker(self, response, language, challenge='verify'):
        self.assertEqual(response.status_code, 302)
        redirect = urlsplit(response['Location'])
        self.assertEqual(redirect.path, f'/{language}/security/{challenge}/')
        query = parse_qs(redirect.query)
        self.assertEqual(set(query), {'invitation'})
        marker = query['invitation'][0]
        self.assertRegex(marker, r'^[0-9a-f]{64}$')
        return marker

    def verify(self, client, device, language, marker, *, token=None):
        return client.post(f'/{language}/security/verify/?invitation={marker}', {'token': token or otp(device)})

    def assert_pending(self, user, invitation):
        self.assertFalse(Membership.objects.filter(user=user, organization=self.target).exists())
        self.assertFalse(NoticeAcknowledgement.objects.filter(user=user, organization=self.target).exists())
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)

    def finish_notice(self, client, user, language):
        path = f'/{language}/information/'
        self.assertRedirects(client.post(path, practice_form_data(client, path)),
                             f'/{language}/app/', fetch_redirect_response=False)
        self.assertTrue(Membership.objects.filter(user=user, organization=self.target, role='clinician', active=True).exists())
        self.assertTrue(NoticeAcknowledgement.objects.filter(user=user, organization=self.target, language=language).exists())

    def test_existing_clinician_returns_to_explicit_accept_and_current_notice_in_each_language(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language):
                user, device = self.existing_clinician('returning-' + language)
                invitation, raw, link = self.invite(user.email, language)
                client = Client()
                gate = self.login(client, user, link, language)
                marker = self.marker(gate, language)
                self.assertNotIn(raw, gate['Location'])
                session = client.session[SESSION_KEY]
                self.assertEqual(set(session), {'actor', 'digest', 'started_at'})
                self.assertEqual((session['actor'], session['digest']), (str(user.pk), invitation.token_hash))
                self.assertNotIn(raw, json.dumps(dict(client.session)))
                invalid = self.verify(client, device, language, marker, token='not-a-fictional-code')
                self.assertEqual(invalid.status_code, 200)
                self.assert_pending(user, invitation)
                self.assertNotIn(PENDING_NOTICE_INVITATION_DIGEST, client.session)

                resume = f'/{language}/invitation/resume/?invitation={marker}'
                self.assertRedirects(self.verify(client, device, language, marker), resume, fetch_redirect_response=False)
                accepted_page = client.get(resume)
                for text in ('id="practice-invitation-accept-form"', 'id="resumed-inviting-practice"', self.target.name):
                    self.assertContains(accepted_page, text)
                self.assertNotContains(accepted_page, raw)
                self.assertContains(accepted_page, f'lang="{language}" dir="{"rtl" if language == "ar" else "ltr"}"')
                self.assert_pending(user, invitation)
                self.assertNotIn(PENDING_NOTICE_INVITATION_DIGEST, client.session)
                self.assertRedirects(client.post(resume), f'/{language}/information/', fetch_redirect_response=False)
                self.assert_pending(user, invitation)
                self.assertNotIn(SESSION_KEY, client.session)
                self.assertEqual(client.session[PENDING_NOTICE_INVITATION_DIGEST], invitation.token_hash)
                self.finish_notice(client, user, language)
                self.assertIn('organization', client.session)
                self.assertEqual(client.session['organization'], str(self.target.pk))
                self.assertTrue(Membership.objects.filter(user=user, organization=self.original, active=True).exists())
                self.assertEqual(client.get(resume).status_code, 410)

    def test_new_clinician_signup_keeps_existing_notice_then_ordinary_mfa_enrollment(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language):
                username = 'fictional-first-mfa-' + language
                invitation, _raw, link = self.invite(username + '@example.test', language)
                client = Client()
                self.assertContains(client.get(link), 'name="instruction_language"')
                signup = client.post(link, {'username': username, 'instruction_language': language,
                                            'password1': PASSWORD, 'password2': PASSWORD})
                self.assertRedirects(signup, f'/{language}/information/', fetch_redirect_response=False)
                user = User.objects.get(username=username)
                self.assert_pending(user, invitation)
                self.finish_notice(client, user, language)
                self.assertNotIn(SESSION_KEY, client.session)
                setup = f'/{language}/security/setup/'
                self.assertRedirects(client.get(f'/{language}/app/'), setup, fetch_redirect_response=False)
                self.assertEqual(client.get(setup).status_code, 200)
                device = TOTPDevice.objects.get(user=user, confirmed=False)
                codes = client.post(setup, {'password': PASSWORD, 'token': otp(device)})
                self.assertContains(codes, f'href="/{language}/app/"')
                self.assertNotContains(codes, '/invitation/resume/')
                self.assertEqual(RecoveryCode.objects.filter(user=user).count(), 8)
                self.assertEqual(client.get(f'/{language}/app/').status_code, 200)

    def test_forced_mfa_enrollment_keeps_recovery_codes_then_resumes_original_invite(self):
        user, _device = self.existing_clinician('enrolment', confirmed=False)
        invitation, raw, link = self.invite(user.email, 'fr')
        client = Client()
        gate = self.login(client, user, link, 'fr')
        marker = self.marker(gate, 'fr', 'setup')
        self.assertNotIn(raw, gate['Location'])
        setup = gate['Location']
        self.assertEqual(client.get(setup).status_code, 200)
        self.assert_pending(user, invitation)
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        codes = client.post(setup, {'password': PASSWORD, 'token': otp(device)})
        resume = f'/fr/invitation/resume/?invitation={marker}'
        self.assertContains(codes, 'class="recovery-list"')
        self.assertContains(codes, f'href="{resume}"')
        self.assertEqual(RecoveryCode.objects.filter(user=user).count(), 8)
        self.assertContains(client.get(resume), self.target.name)
        self.assert_pending(user, invitation)
        self.assertRedirects(client.post(resume), '/fr/information/', fetch_redirect_response=False)
        self.finish_notice(client, user, 'fr')

    def test_recovery_code_and_language_switch_continue_only_for_a_bound_challenge(self):
        import hashlib

        user, _device = self.existing_clinician('recovery')
        invitation, raw, link = self.invite(user.email, 'en')
        client = Client()
        challenge = self.login(client, user, link, 'en')
        marker = self.marker(challenge, 'en')
        switched = client.post('/i18n/setlang/', {'language': 'ar', 'next': challenge['Location']})
        localized = f'/ar/security/verify/?invitation={marker}'
        self.assertRedirects(switched, localized, fetch_redirect_response=False)
        first_code = 'fictional-recovery-for-invitation'
        second_code = 'fictional-recovery-for-navbar'
        for code in (first_code, second_code):
            RecoveryCode.objects.create(user=user, digest=hashlib.sha256(code.encode()).hexdigest())

        # The unmarked navbar verification retains its normal old-cabinet destination.
        plain = client.post('/ar/security/verify/', {'token': first_code})
        self.assertRedirects(plain, '/ar/app/', fetch_redirect_response=False)
        self.assert_pending(user, invitation)
        resume = f'/ar/invitation/resume/?invitation={marker}'
        destination = client.post(localized, {'token': second_code})
        self.assertRedirects(destination, resume, fetch_redirect_response=False)
        self.assertNotIn(raw, resume)
        self.assert_pending(user, invitation)
        self.assertEqual(RecoveryCode.objects.filter(user=user).count(), 0)

    def test_wrong_account_and_external_destination_never_park_or_reveal_invitation(self):
        user, device = self.existing_clinician('wrong-account')
        invitation, _raw, link = self.invite('another-recipient@example.test', 'en')
        client = Client()
        gate = self.login(client, user, link, 'en')
        self.assertRedirects(gate, '/en/security/verify/', fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, client.session)
        destination = client.post('/en/security/verify/?next=https://outside.example/another-invite/', {'token': otp(device)})
        self.assertRedirects(destination, '/en/app/', fetch_redirect_response=False)
        self.assertEqual(client.get('/en/invitation/resume/?invitation=' + invitation.token_hash).status_code, 410)
        self.assert_pending(user, invitation)

    def test_replaced_revoked_or_expired_continuation_cannot_grant_affiliation(self):
        for variant in ('replaced', 'revoked', 'expired', 'timeout'):
            with self.subTest(variant=variant):
                user, device = self.existing_clinician('unavailable-' + variant)
                invitation, raw, link = self.invite(user.email, 'en')
                client = Client()
                original = self.marker(self.login(client, user, link, 'en'), 'en')
                marker = original
                if variant == 'replaced':
                    new_invite, _raw, replacement = self.invite(user.email, 'en')
                    marker = self.marker(client.get(replacement), 'en')
                    self.assertNotEqual(marker, original)
                elif variant in ('revoked', 'expired'):
                    if variant == 'revoked':
                        invitation.revoked = True
                    else:
                        invitation.expires_at = timezone.now() - timedelta(days=1)
                    invitation.save()
                else:
                    session = client.session
                    session[SESSION_KEY]['started_at'] -= TTL_SECONDS + 1
                    session.save()

                verified = self.verify(client, device, 'en', marker)
                resume = f'/en/invitation/resume/?invitation={marker}'
                expected = '/en/app/' if variant == 'timeout' else resume
                self.assertRedirects(verified, expected, fetch_redirect_response=False)
                old_resume = f'/en/invitation/resume/?invitation={original}'
                unavailable = client.post(old_resume)
                self.assertContains(unavailable, 'Invitation unavailable', status_code=410)
                self.assertNotContains(unavailable, self.target.name, status_code=410)
                self.assertNotContains(unavailable, raw, status_code=410)
                self.assert_pending(user, invitation)
                self.assertNotIn(PENDING_NOTICE_INVITATION_DIGEST, client.session)
                if variant == 'replaced':
                    self.assertEqual(client.session[SESSION_KEY]['digest'], new_invite.token_hash)
                    self.assertContains(client.get(resume), self.target.name)
                else:
                    self.assertNotIn(SESSION_KEY, client.session)
