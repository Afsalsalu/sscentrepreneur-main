from unittest.mock import Mock, patch
from json import loads

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from exam.models import MainExamProgress
from exam.models.user_registration import MainExamRegistration, TemporaryUser

from .models import QualifiedUserSync
from .services import sync_qualified_user


@override_settings(
    SSCEGOV_SYNC_ENDPOINT="https://sscegov.example/api/integrations/sscentrepreneur/exam-qualified-user/",
    SSCEGOV_SYNC_API_KEY="test-api-key",
    SSCEGOV_SYNC_HMAC_SECRET="test-hmac-secret",
)
class QualifiedUserSyncTests(TestCase):
    def make_candidate(self, passed=True):
        user = get_user_model().objects.create_user(
            username="123456789012",
            password="9876543210",
            email="candidate@example.com",
            usertype="centre",
        )
        candidate = TemporaryUser.objects.create(
            user=user,
            name="Qualified Candidate",
            mobile="9876543210",
            email="candidate@example.com",
            state="Kerala",
            district="Kollam",
            panchayat="Test Panchayat",
            ward_number="4",
            gender="male",
            aadhaar_number="123456789012",
            address="Test address",
            main_exam_passed=passed,
        )
        MainExamRegistration.objects.create(
            user=user,
            username="TEC123456789012",
            password="9876543210",
            mobile="9876543210",
            is_passed=passed,
        )
        MainExamProgress.objects.create(
            user=user,
            status="Passed" if passed else "Failed Attempt 1",
            total_questions=50,
            correct_answers=40 if passed else 1,
            completed_at=timezone.now(),
        )
        return candidate

    @patch("integrations.services.requests.post")
    def test_qualified_user_is_synced_and_retry_metadata_is_saved(self, post):
        post.return_value = Mock(status_code=201, text='{"ok": true}')
        candidate = self.make_candidate()

        result = sync_qualified_user(candidate)

        self.assertTrue(result.success)
        sync = QualifiedUserSync.objects.get(candidate=candidate)
        self.assertEqual(sync.status, QualifiedUserSync.SUCCEEDED)
        self.assertEqual(sync.attempt_count, 1)
        self.assertIsNone(sync.next_retry_at)
        body = post.call_args.kwargs["data"]
        sent = loads(body.decode())
        self.assertEqual(sent["mobile"], "9876543210")
        self.assertNotEqual(sent["password_hash"], "9876543210")

    @patch("integrations.services.requests.post")
    def test_failed_exam_is_rejected_without_api_call(self, post):
        candidate = self.make_candidate(passed=False)

        result = sync_qualified_user(candidate)

        self.assertFalse(result.success)
        self.assertEqual(result.status, QualifiedUserSync.REJECTED)
        post.assert_not_called()
        self.assertEqual(QualifiedUserSync.objects.get(candidate=candidate).attempt_count, 0)

    @patch("integrations.services.requests.post")
    def test_temporary_destination_failure_is_retryable(self, post):
        post.return_value = Mock(status_code=503, text="temporarily unavailable")
        candidate = self.make_candidate()

        result = sync_qualified_user(candidate)

        sync = QualifiedUserSync.objects.get(candidate=candidate)
        self.assertFalse(result.success)
        self.assertEqual(sync.status, QualifiedUserSync.FAILED)
        self.assertEqual(sync.attempt_count, 1)
        self.assertIsNotNone(sync.next_retry_at)
