"""Create and repair local centre accounts after a successful main exam."""

import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from web.models import CentreUserAccount


class LocalCentreUserAccountError(Exception):
    """Raised when a passed candidate cannot be persisted locally."""


def _digits(value, field_name, length):
    value = str(value or "").strip()
    if not value.isdigit() or len(value) != length:
        raise LocalCentreUserAccountError(
            f"{field_name} must contain exactly {length} digits"
        )
    return int(value)


def _choice_value(value, choices, field_name):
    value = str(value or "").strip()
    if not value:
        raise LocalCentreUserAccountError(f"{field_name} is required")

    compact = re.sub(r"[^a-z0-9]", "", value.casefold())
    for key, label in choices:
        if value == key or value.casefold() == label.casefold():
            return key
        if compact and compact == re.sub(r"[^a-z0-9]", "", label.casefold()):
            return key
    raise LocalCentreUserAccountError(f"{field_name} is invalid")


def _rural_area_value(value):
    if not value:
        return None
    aliases = {
        "panchayat": "panchayat",
        "panchayath": "panchayat",
        "municipality": "municipality",
        "muncipality": "municipality",
        "corporation": "corporation",
    }
    return aliases.get(str(value).strip().casefold())


def _has_value(value):
    return value not in (None, "")


def _account_values(user, temp_user, username):
    username = str(username or "").strip()
    if not username:
        raise LocalCentreUserAccountError("username is required")

    owner_centre = str(temp_user.name or "").strip()
    if not owner_centre:
        raise LocalCentreUserAccountError("owner name is required")

    email = str(temp_user.email or "").strip()
    if not email:
        raise LocalCentreUserAccountError("email is required")

    address = str(temp_user.address or "").strip()
    location = address
    if temp_user.lattitude is not None and temp_user.longitude is not None:
        location = f"{temp_user.lattitude},{temp_user.longitude}"
    if not location:
        raise LocalCentreUserAccountError("location is required")

    mobile = _digits(temp_user.mobile, "mobile", 10)
    aadhaar_number = _digits(temp_user.aadhaar_number, "aadhaar number", 12)
    state = _choice_value(
        temp_user.state, CentreUserAccount.STATE_CHOICES, "state"
    )
    rural_areas = _rural_area_value(temp_user.local_body)

    values = {
        "user": user,
        "username": username,
        "owner_centre": owner_centre,
        "mobile": mobile,
        "photo": temp_user.photo if temp_user.photo else None,
        "aadhaar_number": aadhaar_number,
        "email": email,
        "state": state,
        "district": str(temp_user.district or "").strip() or None,
        "rural_areas": rural_areas,
        "ward_number": str(temp_user.ward_number or "").strip() or None,
        "centre_phone_number": mobile,
        "centre_name": str(temp_user.panchayat or "").strip() or None,
        "centre_email": email,
        # CentreUserAccount.another_name is optional at the form/model level,
        # but its existing database column is NOT NULL.  Store the safe blank
        # value and never use it to replace an existing non-empty value.
        "another_name": str(temp_user.another_name or "").strip(),
        "centre_owner_address": address or None,
        "location": location,
        "is_approved": False,
        "is_olduser": False,
    }
    return values


def ensure_centre_user_account_for_pass(*, user, temp_user, username=None):
    """Create or repair one local centre account for a passed candidate.

    The authentication user is the idempotency key.  Existing non-empty
    values are preserved; only missing values are repaired from the exam
    registration.  The caller should invoke SSCEGOV sync after this function
    returns successfully and the surrounding transaction has committed.
    """

    username = username or getattr(user, "username", "")
    values = _account_values(user, temp_user, username)
    update_values = {
        key: value
        for key, value in values.items()
        if key != "user" and _has_value(value)
    }

    try:
        with transaction.atomic():
            account = (
                CentreUserAccount.objects.select_for_update()
                .filter(user=user)
                .first()
            )
            created = account is None
            if created:
                account = CentreUserAccount(**values)
                account.full_clean()
                account.save(force_insert=True)
            else:
                fields_to_update = []
                for field_name, value in update_values.items():
                    if not _has_value(getattr(account, field_name, None)):
                        setattr(account, field_name, value)
                        fields_to_update.append(field_name)
                if fields_to_update:
                    account.save(update_fields=fields_to_update)
            return account, created
    except (ValidationError, IntegrityError) as exc:
        raise LocalCentreUserAccountError(
            f"local CentreUserAccount persistence failed ({type(exc).__name__})"
        ) from exc
