
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from integrations.services import SyncResult, build_qualified_user_payload
from web.models import CentreUserAccount

from .models import MainExamOption, MainExamProgress, MainExamQuestion
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


class FinalExamAccountSyncTests(TransactionTestCase):
    def test_real_pass_then_details_entry_syncs_created_account(self):
        source_user = get_user_model().objects.create_user(
            username='final-pass-source',
            password='source-password',
            email='final-pass@example.com',
        )
        candidate = TemporaryUser.objects.create(
            user=source_user,
            name='Final Pass Candidate',
            mobile='9876543211',
            email='final-pass@example.com',
            state='kerala',
            district='Ernakulam',
            local_body='Panchayath',
            panchayat='Test Panchayat',
            ward_number='1',
            gender='male',
            aadhaar_number='123456789013',
            address='Test address',
            main_exam_passed=False,
        )
        question = MainExamQuestion.objects.create(question_text='Final exam test')
        option = MainExamOption.objects.create(
            question=question,
            option='Correct answer',
            is_correct=True,
        )
        client = Client()
        client.force_login(source_user)

        # This is the browser's live final-pass endpoint used by
        # main-exam.js, not the unused main_exam POST branch.
        pass_response = client.post(
            reverse('exam:submit_exam'),
            {f'question_{question.pk}': str(option.pk)},
        )
        self.assertEqual(pass_response.status_code, 200)
        self.assertTrue(pass_response.json()['pass_exam'])
        self.assertTrue(
            MainExamProgress.objects.filter(
                user=source_user,
                status='Passed',
            ).exists()
        )

        details_data = {
            'owner_centre': 'Final Pass Centre',
            'mobile': '9876543211',
            'aadhaar_number': '123456789013',
            'email': 'final-pass@example.com',
            'centre_phone_number': '9876543211',
            'state': 'kerala',
            'district': 'Ernakulam',
            'location': '10.000,76.000',
            'centre_name': 'Final Pass Centre',
            'another_name': '-',
            'is_active': 'on',
        }
        with patch(
            'exam.views.sync_qualified_user',
            return_value=SyncResult(True, 'succeeded', 'ok', 200),
        ) as sync_mock, patch(
            'exam.views.generate_username',
            return_value='generated-final-pass-user',
        ), patch('exam.views.ApiClient'), patch(
            'exam.views.transactional_emails_api.TransactionalEmailsApi'
        ):
            details_response = client.post(
                reverse('exam:details_entry'),
                details_data,
            )

        self.assertEqual(details_response.status_code, 302)
        created_account = CentreUserAccount.objects.get(
            username='generated-final-pass-user'
        )
        payload = build_qualified_user_payload(created_account)
        self.assertEqual(payload['exam_status'], 'Passed')
        self.assertEqual(payload['source_candidate_id'], candidate.pk)
        sync_mock.assert_called_once()
        synced_account = sync_mock.call_args.args[0]
        self.assertEqual(synced_account.pk, created_account.pk)
