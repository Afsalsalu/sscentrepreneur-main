
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase

from integrations.services import SyncResult
from web.models import CentreUserAccount

from .models import MainExamProgress
from .models.user_registration import TemporaryUser
from .views import _queue_qualified_user_sync


class QualifiedUserSyncTriggerTests(TestCase):
    def test_passed_centre_user_sync_is_queued_until_commit(self):
        user = get_user_model().objects.create_user(
            username='passed-source-user',
            password='source-password',
            email='passed@example.com',
        )
        candidate = TemporaryUser.objects.create(
            user=user,
            name='Passed Candidate',
            mobile='9876543210',
            email='passed@example.com',
            state='kerala',
            district='Ernakulam',
            local_body='Panchayath',
            panchayat='Test Panchayat',
            ward_number='1',
            gender='male',
            aadhaar_number='123456789012',
            address='Test address',
            main_exam_passed=True,
        )
        MainExamProgress.objects.create(
            user=user,
            status='Passed',
            total_questions=1,
            correct_answers=1,
            attempt_number=1,
        )
        centre_user = CentreUserAccount.objects.create(
            user=user,
            username='SSC000001',
            owner_centre=candidate.name,
            mobile=9876543210,
            aadhaar_number=123456789012,
            email=candidate.email,
            state=candidate.state,
            district=candidate.district,
            rural_areas=candidate.local_body,
            centre_phone_number=9876543210,
            centre_name=candidate.panchayat,
            centre_email=candidate.email,
            centre_owner_address=candidate.address,
            location=candidate.address,
        )

        with patch(
            'exam.views.sync_qualified_user',
            return_value=SyncResult(True, 'succeeded', 'ok', 200),
        ) as sync_mock:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                with transaction.atomic():
                    _queue_qualified_user_sync(centre_user)

            sync_mock.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()

        sync_mock.assert_called_once()
        synced_account = sync_mock.call_args.args[0]
        self.assertEqual(synced_account.pk, centre_user.pk)
        self.assertEqual(synced_account.user_id, user.pk)
