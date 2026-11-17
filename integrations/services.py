import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import requests
from django.conf import settings
from django.contrib.auth.hashers import identify_hasher
from django.utils import timezone

from exam.models import MainExamProgress
from exam.models.user_registration import TemporaryUser
from web.models import CentreUserAccount


class NotQualifiedError(ValueError):
    pass


@dataclass
class SyncResult:
    success: bool
    status: str
    message: str
    http_status: int | None = None


def _normalise_mobile(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if len(digits) != 10:
        raise NotQualifiedError('Candidate mobile number is not a valid 10-digit number')
    return digits


def _resolve_sync_sources(source):
    """Return the registration candidate and optional source centre account.

    Final-exam completion creates the ``CentreUserAccount`` that is sent to
    SSCEGOV.  The original payload is built from the related ``TemporaryUser``
    because that record contains the exam-registration fields.  Supporting
    both objects keeps the existing service API compatible while allowing the
    trigger and management command to use the exact persisted centre account.
    """
    if isinstance(source, CentreUserAccount):
        candidate = (
            TemporaryUser.objects.filter(user=source.user)
            .order_by('-id')
            .first()
        )
        if candidate is None:
            # The details-entry flow creates the centre login user after the
            # final exam user has passed. Match that new account back to the
            # unique registration identifiers without weakening pass checks.
            candidate = (
                TemporaryUser.objects.filter(
                    mobile=str(source.mobile),
                )
                .order_by('-id')
                .first()
            )
        if candidate is None and source.aadhaar_number:
            candidate = (
                TemporaryUser.objects.filter(
                    aadhaar_number=str(source.aadhaar_number),
                )
                .order_by('-id')
                .first()
            )
        if candidate is None:
            raise NotQualifiedError(
                'Centre account has no matching exam registration candidate'
            )
        return candidate, source
    return source, None


def build_qualified_user_payload(source):
    candidate, centre_user = _resolve_sync_sources(source)
    source_user = candidate.user
    if source_user is None:
        raise NotQualifiedError('Candidate has no source authentication user')
    passed_progress = (
        MainExamProgress.objects.filter(user=source_user, status='Passed')
        .order_by('-completed_at', '-id')
        .first()
    )
    if passed_progress is None:
        raise NotQualifiedError('Candidate has not successfully passed the final exam')

    mobile = _normalise_mobile(candidate.mobile)
    email = (source_user.email or candidate.email or '').strip().lower()
    if not email:
        raise NotQualifiedError('Qualified candidate has no email address')
    completion_time = passed_progress.completed_at or timezone.now()
    if candidate.lattitude is not None and candidate.longitude is not None:
        location = f'{candidate.lattitude},{candidate.longitude}'
    else:
        location = candidate.address or ''
    password_hash = None
    if source_user.password:
        try:
            identify_hasher(source_user.password)
            password_hash = source_user.password
        except (ValueError, TypeError):
            password_hash = None
    full_name = (candidate.name or '').strip()
    if not full_name and centre_user is not None:
        full_name = (centre_user.owner_centre or '').strip()
    username = (source_user.username or '').strip()
    if centre_user is not None and centre_user.username:
        username = centre_user.username.strip()

    return {
        'schema_version': 1,
        'source_system': 'sscentrepreneur',
        'source_user_id': source_user.pk,
        'source_candidate_id': candidate.pk,
        'full_name': full_name,
        'username': username,
        'email': email,
        'mobile': mobile,
        'address': candidate.address or '',
        'centre': {
            'owner_name': full_name,
            'name': candidate.panchayat or '',
            'state': candidate.state or '',
            'district': candidate.district or '',
            'taluk': '',
            'local_body': candidate.local_body or '',
            'ward_number': candidate.ward_number or '',
            'centre_email': email,
            'centre_phone_number': mobile,
            'location': location,
        },
        'aadhaar_number': str(candidate.aadhaar_number or ''),
        'exam_status': 'Passed',
        'exam_completed_at': completion_time.isoformat(),
        'password_hash': password_hash,
    }


def sync_qualified_user(source):
    try:
        payload = build_qualified_user_payload(source)
    except NotQualifiedError as exc:
        return SyncResult(False, 'rejected', str(exc))

    endpoint = str(getattr(settings, 'SSCEGOV_SYNC_ENDPOINT', '')).strip()
    api_key = str(
        getattr(settings, 'SSCEGOV_INTEGRATION_API_KEY', '')
        or getattr(settings, 'SSCEGOV_SYNC_API_KEY', '')
    ).strip()
    hmac_secret = str(
        getattr(settings, 'SSCEGOV_INTEGRATION_HMAC_SECRET', '')
        or getattr(settings, 'SSCEGOV_SYNC_HMAC_SECRET', '')
    ).strip()
    if not endpoint.startswith('https://') or not api_key or not hmac_secret:
        return SyncResult(
            False,
            'failed',
            'SSCEGOV sync requires an HTTPS endpoint, API key, and HMAC secret',
        )

    body = json.dumps(
        payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False
    ).encode('utf-8')
    timestamp = str(int(time.time()))
    signature = hmac.new(
        hmac_secret.encode('utf-8'),
        f'{timestamp}.'.encode('utf-8') + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-SSCEGOV-API-Key': api_key,
        'X-SSCEGOV-Timestamp': timestamp,
        'X-SSCEGOV-Signature': signature,
        'X-SSCEGOV-Idempotency-Key': (
            f'sscentrepreneur:final-exam:{payload["source_candidate_id"]}'
        ),
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
    except requests.RequestException as exc:
        return SyncResult(
            False,
            'failed',
            f'Destination request failed: {exc.__class__.__name__}',
        )

    if 200 <= response.status_code < 300:
        return SyncResult(True, 'succeeded', 'Qualified user synchronized', response.status_code)
    return SyncResult(
        False,
        'failed',
        f'Destination returned HTTP {response.status_code}',
        response.status_code,
    )
