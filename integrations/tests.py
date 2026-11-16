from django.test import SimpleTestCase

from .services import NotQualifiedError, _normalise_mobile


class QualifiedUserSyncTests(SimpleTestCase):
    def test_mobile_normalisation_accepts_ten_digits(self):
        self.assertEqual(_normalise_mobile('987-654-3210'), '9876543210')

    def test_mobile_normalisation_rejects_invalid_values(self):
        with self.assertRaises(NotQualifiedError):
            _normalise_mobile('1234')
