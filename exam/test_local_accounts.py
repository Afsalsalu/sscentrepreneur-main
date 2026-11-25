from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from exam.local_accounts import (
    LocalCentreUserAccountError,
    ensure_centre_user_account_for_pass,
)
from exam.models import MainExamProgress, MainExamQuestion, MainExamOption
from exam.models.user_registration import MainExamRegistration, TemporaryUser
from web.models import CentreUserAccount


class LocalCentreUserAccountTests(TestCase):
    def make_candidate(self, *, username="candidate-1", **overrides):
        user = get_user_model().objects.create_user(
            username=username,
            email=overrides.pop("email", f"{username}@example.com"),
            password="test-password",
        )
        defaults = {
            "user": user,
            "name": "Exam Candidate",
            "mobile": "9876543210",
            "email": user.email,
            "another_name": "Parent",
            "state": "Kerala",
            "district": "Ernakulam",
            "local_body": "Panchayath",
            "panchayat": "Sample Panchayat",
            "ward_number": "1",
            "gender": "male",
            "aadhaar_number": "123456789012",
            "address": "Sample address",
        }
        defaults.update(overrides)
        return user, TemporaryUser.objects.create(**defaults)

    def test_passed_exam_creates_local_centre_account(self):
        user, temp_user = self.make_candidate()

        account, created = ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )

        self.assertTrue(created)
        self.assertEqual(account.user_id, user.pk)
        self.assertEqual(account.owner_centre, temp_user.name)
        self.assertEqual(account.state, "kerala")
        self.assertEqual(account.rural_areas, "panchayat")
        self.assertEqual(account.another_name, "Parent")
        self.assertEqual(CentreUserAccount.objects.count(), 1)

    def test_repeated_pass_callback_is_idempotent(self):
        user, temp_user = self.make_candidate()

        first, first_created = ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )
        first.another_name = "Existing Parent"
        first.save(update_fields=["another_name"])
        temp_user.another_name = None
        temp_user.save(update_fields=["another_name"])
        second, second_created = ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-2"
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CentreUserAccount.objects.count(), 1)
        self.assertEqual(second.username, "centre-1")
        self.assertEqual(second.another_name, "Existing Parent")

    def test_duplicate_user_does_not_create_second_account(self):
        user, temp_user = self.make_candidate()
        ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )
        ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )

        self.assertEqual(CentreUserAccount.objects.filter(user=user).count(), 1)

    def test_missing_optional_fields_do_not_block_valid_creation(self):
        user, temp_user = self.make_candidate(another_name=None)
        temp_user.photo = None
        temp_user.save(update_fields=["another_name", "photo"])

        account, created = ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )

        self.assertTrue(created)
        self.assertEqual(account.another_name, "")
        self.assertFalse(account.photo)

    def test_invalid_required_data_gives_safe_error(self):
        user, temp_user = self.make_candidate(mobile="not-a-mobile")

        with self.assertRaises(LocalCentreUserAccountError):
            ensure_centre_user_account_for_pass(
                user=user, temp_user=temp_user, username="centre-1"
            )

        self.assertFalse(CentreUserAccount.objects.filter(user=user).exists())

    def test_integrity_error_gives_safe_error(self):
        user, temp_user = self.make_candidate()

        with patch.object(
            CentreUserAccount,
            "save",
            side_effect=IntegrityError("duplicate key"),
        ):
            with self.assertRaises(LocalCentreUserAccountError):
                ensure_centre_user_account_for_pass(
                    user=user, temp_user=temp_user, username="centre-1"
                )

        self.assertFalse(CentreUserAccount.objects.filter(user=user).exists())

    def test_transaction_rollback_does_not_silently_lose_local_account(self):
        user, temp_user = self.make_candidate()

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                ensure_centre_user_account_for_pass(
                    user=user, temp_user=temp_user, username="centre-1"
                )
                raise RuntimeError("test rollback")

        self.assertFalse(CentreUserAccount.objects.filter(user=user).exists())

    def test_new_account_appears_in_correct_local_list(self):
        user, temp_user = self.make_candidate()
        ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )

        self.assertTrue(
            CentreUserAccount.objects.filter(
                user=user, state="kerala", district=temp_user.district
            ).exists()
        )

    def test_company_branch_financial_year_scope_is_not_removed(self):
        user, temp_user = self.make_candidate()
        ensure_centre_user_account_for_pass(
            user=user, temp_user=temp_user, username="centre-1"
        )

        self.assertNotIn("company", CentreUserAccount._meta.fields_map)
        self.assertNotIn("branch", CentreUserAccount._meta.fields_map)
        self.assertNotIn("financial_year", CentreUserAccount._meta.fields_map)


class MainExamLocalAccountRepairTests(TestCase):
    def make_candidate(self):
        user = get_user_model().objects.create_user(
            username="exam-candidate", email="exam@example.com", password="test-password"
        )
        temp_user = TemporaryUser.objects.create(
            user=user,
            name="Exam Candidate",
            mobile="9876543210",
            email="exam@example.com",
            state="Kerala",
            district="Ernakulam",
            local_body="Panchayath",
            panchayat="Sample Panchayat",
            ward_number="1",
            gender="male",
            aadhaar_number="123456789012",
            address="Sample address",
        )
        question = MainExamQuestion.objects.create(question_text="Pass question")
        option = MainExamOption.objects.create(
            question=question, option="Correct", is_correct=True
        )
        return user, temp_user, question, option

    def test_main_exam_pass_creates_local_account_without_main_registration(self):
        user, temp_user, question, option = self.make_candidate()
        client = self.client
        client.force_login(user)
        session = client.session
        session["exam_questions"] = [question.pk]
        session.save()

        with patch("exam.views.main_email_send"), patch(
            "exam.views.sync_qualified_user"
        ) as sync:
            sync.return_value.success = True
            response = client.post(
                "/exam/main-exam/",
                {f"question_{question.pk}": option.pk},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(CentreUserAccount.objects.filter(user=user).exists())
        self.assertTrue(
            MainExamProgress.objects.filter(user=user, status="Passed").exists()
        )
        sync.assert_called_once_with(temp_user)
        self.assertFalse(MainExamRegistration.objects.filter(user=user).exists())

    def test_repeated_main_exam_pass_callback_repairs_without_duplicate(self):
        user, temp_user, question, option = self.make_candidate()
        MainExamProgress.objects.create(
            user=user,
            attempt_number=1,
            correct_answers=1,
            total_questions=1,
            status="Passed",
        )
        client = self.client
        client.force_login(user)
        session = client.session
        session["exam_questions"] = [question.pk]
        session.save()

        response = client.post(
            "/exam/main-exam/",
            {f"question_{question.pk}": option.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CentreUserAccount.objects.filter(user=user).count(), 1)

    def test_missing_required_data_fails_safely_and_is_logged(self):
        user, temp_user, question, option = self.make_candidate()
        temp_user.mobile = "invalid"
        temp_user.save(update_fields=["mobile"])
        client = self.client
        client.force_login(user)
        session = client.session
        session["exam_questions"] = [question.pk]
        session.save()

        with patch("exam.views.main_email_send"), patch(
            "exam.views.sync_qualified_user"
        ) as sync, self.assertLogs("exam.views", level="ERROR") as logs:
            response = client.post(
                "/exam/main-exam/",
                {f"question_{question.pk}": option.pk},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CentreUserAccount.objects.filter(user=user).exists())
        sync.assert_not_called()
        self.assertIn(f"user_id={user.pk}", "\n".join(logs.output))
        self.assertIn(f"candidate_id={temp_user.pk}", "\n".join(logs.output))
