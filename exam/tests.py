
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, RequestFactory, SimpleTestCase
from django.urls import reverse

from exam import views


class RegistrationLocationAvailabilityTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post_location(self, latitude, longitude):
        request = self.factory.post(
            reverse("exam:check_location"),
            data=json.dumps({"latitude": latitude, "longitude": longitude}),
            content_type="application/json",
        )
        return views.check_location(request)

    @staticmethod
    def payload(response):
        return json.loads(response.content)

    def test_available_coordinate_returns_valid_true(self):
        with patch.object(views.TemporaryUser.objects, "all", return_value=[]), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[]
        ):
            response = self.post_location("10.123456", "76.654321")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.payload(response)["valid"])

    def test_coordinate_at_exactly_one_km_is_blocked(self):
        existing_user = SimpleNamespace(lattitude=10.0, longitude=76.0)
        with patch.object(views.TemporaryUser.objects, "all", return_value=[existing_user]), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[]
        ), patch.object(views, "haversine", return_value=1.0):
            response = self.post_location(10.1, 76.1)

        payload = self.payload(response)
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["nearest_distance_km"], 1.0)

    def test_coordinate_outside_one_km_is_available(self):
        existing_user = SimpleNamespace(lattitude=10.0, longitude=76.0)
        with patch.object(views.TemporaryUser.objects, "all", return_value=[existing_user]), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[]
        ), patch.object(views, "haversine", return_value=1.0001):
            response = self.post_location(10.1, 76.1)

        self.assertTrue(self.payload(response)["valid"])

    def test_invalid_coordinates_return_http_400(self):
        response = self.post_location(91, 76)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.payload(response)["valid"])

    def test_temporary_user_coordinates_are_checked(self):
        existing_user = SimpleNamespace(lattitude=10.123456, longitude=76.654321)
        with patch.object(views.TemporaryUser.objects, "all", return_value=[existing_user]), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[]
        ):
            response = self.post_location(10.123456, 76.654321)

        self.assertFalse(self.payload(response)["valid"])
        self.assertEqual(self.payload(response)["conflict_type"], "temporary_user")

    def test_centre_user_plain_coordinates_are_checked(self):
        existing_centre = SimpleNamespace(location="10.123456,76.654321")
        with patch.object(views.TemporaryUser.objects, "all", return_value=[]), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[existing_centre]
        ):
            response = self.post_location(10.123456, 76.654321)

        self.assertFalse(self.payload(response)["valid"])
        self.assertEqual(self.payload(response)["conflict_type"], "centre_user")

    def test_legacy_google_maps_coordinates_are_checked(self):
        existing_centre = SimpleNamespace(
            location="https://www.google.com/maps/@10.123456,76.654321,17z!3d10.123456!2d76.654321"
        )
        with patch.object(views.TemporaryUser.objects, "all", return_value=[]), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[existing_centre]
        ):
            response = self.post_location(10.123456, 76.654321)

        self.assertFalse(self.payload(response)["valid"])
        self.assertEqual(self.payload(response)["conflict_type"], "centre_user")

    def test_non_post_request_is_rejected(self):
        response = views.check_location(self.factory.get(reverse("exam:check_location")))

        self.assertEqual(response.status_code, 405)

    def test_location_endpoint_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("exam:check_location"),
            data=json.dumps({"latitude": 10.0, "longitude": 76.0}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/exam/userlogin/", response["Location"])


class FinalRegistrationLocationValidationTests(SimpleTestCase):
    def test_final_registration_rechecks_and_blocks_conflicting_location(self):
        state = SimpleNamespace(name="Kerala")
        district = SimpleNamespace(district_name="Ernakulam")
        panchayat = SimpleNamespace(name="Test Panchayat")
        existing_user = SimpleNamespace(lattitude=10.123456, longitude=76.654321)
        request = RequestFactory().post(
            "/exam/temporary_user/",
            data={
                "name": "Test User",
                "email": "test@example.com",
                "mobile": "9876543210",
                "another_name": "Test Parent",
                "state": "1",
                "district": "2",
                "local_body": "Panchayath",
                "panchayat": "3",
                "ward_number": "1",
                "gender": "Other",
                "aadhaar_number": "123456789012",
                "date_of_birth": "1990-01-01",
                "address": "Test address",
                "latitude": "10.123456,76.654321",
            },
        )

        with patch.object(views.RegistrationState.objects, "all", return_value=[]), patch.object(
            views.RegistrationDistrict.objects, "filter", return_value=[]
        ), patch.object(
            views.TemporaryUser.objects, "all", return_value=[existing_user]
        ), patch.object(
            views.CentreUserAccount.objects, "all", return_value=[]
        ), patch.object(
            views, "get_object_or_404", side_effect=[state, district, panchayat]
        ), patch.object(
            views, "_registration_template_context", return_value={"error": "preserved"}
        ) as context_builder, patch.object(views, "render", return_value="rendered"):
            response = views.temporary_user(request)

        self.assertEqual(response, "rendered")
        context_builder.assert_called_once()
        self.assertEqual(
            context_builder.call_args.kwargs["error"],
            views.LOCATION_CONFLICT_MESSAGE,
        )
