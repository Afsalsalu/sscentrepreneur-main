import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth.hashers import identify_hasher
from django.utils import timezone

from exam.models import MainExamProgress
from exam.models.user_registration import MainExamRegistration, TemporaryUser

from .models import QualifiedUserSync


class NotQualifiedError(ValueError):
    """Raised when a candidate is not eligible for the destination portal."""


class SyncConfigurationError(ValueError):
    """Raised when the private integration is not configured safely."""


@dataclass
class SyncResult:
    success: bool
    status: str
    message: str
    http_status: int | None = None


def _normalise_mobile(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 10:
        raise NotQualifiedError("Candidate mobile number is not a valid 10-digit number")
    return digits


def _location(candidate):
    if candidate.lattitude is not None and candidate.longitude is not None:
        return f"{candidate.lattitude},{candidate.longitude}"
    return candidate.address or ""


def _compatible_password_hash(password_hash):
    if not password_hash:
        return None
    try:
        identify_hasher(password_hash)
    except (ValueError, TypeError):
        return None
    return password_hash


def build_qualified_user_payload(candidate: TemporaryUser):
    source_user = candidate.user
    if source_user is None:
        raise NotQualifiedError("Candidate has no source authentication user")

    passed_progress = (
        MainExamProgress.objects.filter(user=source_user, status="Passed")
        .order_by("-completed_at", "-id")
        .first()
    )
    if not candidate.main_exam_passed or passed_progress is None:
        raise NotQualifiedError("Candidate has not successfully passed the final exam")

    # This record is deliberately read for compatibility/audit. Its plaintext
    # password column is never included in the payload.
    MainExamRegistration.objects.filter(user=source_user).first()

    mobile = _normalise_mobile(candidate.mobile)
    email = (source_user.email or candidate.email or "").strip().lower()
    if not email:
        raise NotQualifiedError("Qualified candidate has no email address")

    completion_time = passed_progress.completed_at or timezone.now()
    return {
        "schema_version": 1,
        "source_system": "sscentrepreneur",
        "source_user_id": source_user.pk,
        "source_candidate_id": candidate.pk,
        "full_name": (candidate.name or "").strip(),
        "username": (source_user.username or "").strip(),
        "email": email,
        "mobile": mobile,
        "address": candidate.address or "",
        "centre": {
            "owner_name": (candidate.name or "").strip(),
            "name": candidate.panchayat or "",
            "state": candidate.state or "",
            "district": candidate.district or "",
            "taluk": "",
            "local_body": candidate.local_body or "",
            "ward_number": candidate.ward_number or "",
            "centre_email": email,
            "centre_phone_number": mobile,
            "location": _location(candidate),
        },
        "aadhaar_number": str(candidate.aadhaar_number or ""),
        "exam_status": "Passed",
        "exam_completed_at": completion_time.isoformat(),
        # Both applications use Django's password hash format. This is not a
        # plaintext password and is sent only over the authenticated HTTPS API.
        "password_hash": _compatible_password_hash(source_user.password),
    }


def get_or_create_sync(candidate: TemporaryUser):
    return QualifiedUserSync.objects.get_or_create(
        candidate=candidate,
        defaults={
            "source_user_id": candidate.user_id,
            "source_candidate_id": candidate.pk,
            "idempotency_key": f"sscentrepreneur:final-exam:{candidate.pk}",
        },
    )


def _retry_time(attempt_count):
    delay_minutes = min(60, 2 ** min(max(attempt_count - 1, 0), 6))
    return timezone.now() + timedelta(minutes=delay_minutes)


def sync_qualified_user(candidate_or_sync):
    if isinstance(candidate_or_sync, QualifiedUserSync):
        sync_record = candidate_or_sync
        candidate = sync_record.candidate
    else:
        candidate = candidate_or_sync
        sync_record, _ = get_or_create_sync(candidate)

    try:
        payload = build_qualified_user_payload(candidate)
    except NotQualifiedError as exc:
        sync_record.status = QualifiedUserSync.REJECTED
        sync_record.last_error = str(exc)
        sync_record.next_retry_at = None
        sync_record.last_sync_at = timezone.now()
        sync_record.save()
        return SyncResult(False, sync_record.status, str(exc))

    endpoint = str(getattr(settings, "SSCEGOV_SYNC_ENDPOINT", "")).strip()
    api_key = str(getattr(settings, "SSCEGOV_SYNC_API_KEY", "")).strip()
    hmac_secret = str(getattr(settings, "SSCEGOV_SYNC_HMAC_SECRET", "")).strip()
    if not endpoint.startswith("https://") or not api_key or not hmac_secret:
        message = "SSCEGOV sync requires an HTTPS endpoint, API key, and HMAC secret"
        sync_record.status = QualifiedUserSync.FAILED
        sync_record.last_error = message
        sync_record.last_sync_at = timezone.now()
        sync_record.next_retry_at = _retry_time(sync_record.attempt_count + 1)
        sync_record.save()
        return SyncResult(False, sync_record.status, message)

    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        hmac_secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()

    sync_record.attempt_count += 1
    sync_record.last_sync_at = timezone.now()
    sync_record.last_http_status = None
    sync_record.last_error = ""
    sync_record.response_excerpt = ""
    sync_record.save()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-SSCEGOV-API-Key": api_key,
        "X-SSCEGOV-Timestamp": timestamp,
        "X-SSCEGOV-Signature": signature,
        "X-SSCEGOV-Idempotency-Key": sync_record.idempotency_key,
    }
    try:
        response = requests.post(
            endpoint,
            data=body,
            headers=headers,
            timeout=(5, 15),
            allow_redirects=False,
            verify=True,
        )
        sync_record.last_http_status = response.status_code
        sync_record.response_excerpt = (response.text or "")[:1000]
        if 200 <= response.status_code < 300:
            sync_record.status = QualifiedUserSync.SUCCEEDED
            sync_record.next_retry_at = None
            sync_record.last_error = ""
            sync_record.save()
            return SyncResult(True, sync_record.status, "Qualified user synchronized", response.status_code)

        message = f"Destination returned HTTP {response.status_code}"
    except requests.RequestException as exc:
        message = f"Destination request failed: {exc.__class__.__name__}: {exc}"

    sync_record.status = QualifiedUserSync.FAILED
    sync_record.last_error = message[:4000]
    sync_record.next_retry_at = _retry_time(sync_record.attempt_count)
    sync_record.save()
    return SyncResult(False, sync_record.status, message, sync_record.last_http_status)
