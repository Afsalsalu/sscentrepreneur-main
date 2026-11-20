import logging

from django.conf import settings
from sib_api_v3_sdk import ApiClient, Configuration
from sib_api_v3_sdk.api import transactional_emails_api
from sib_api_v3_sdk.models import SendSmtpEmail
from sib_api_v3_sdk.rest import ApiException

logger = logging.getLogger(__name__)


def _get_brevo_transactional_emails_api():
    api_key = settings.BREVO_API_KEY.strip()
    if not api_key:
        logger.warning("Brevo email skipped: BREVO_API_KEY is not configured.")
        return None

    configuration = Configuration()
    configuration.api_key.update({"api-key": api_key})
    return transactional_emails_api.TransactionalEmailsApi(ApiClient(configuration))


def send_welcome_email(user_registration):
    username = user_registration.user.username
    password = user_registration.mobile
    subject = "Welcome to the Samatwa Service Centre E-Governance LTD"
    html_content = (
        f"<p>Thank you for registering. Your account has been created successfully.</p>"
        f"<p><strong>Centre ID:</strong> {user_registration.id}</p>"
        f"<p><strong>Username:</strong> {username}</p>"
        f"<p><strong>Password:</strong> {password}</p>"
        f"<p>We recommend you change your password after logging in.</p>"
        f"<p>For more information, visit our website: <a href='https://sscegov.com'>https://sscegov.com</a></p>"
        f"<p>Best regards,<br>The SSC Team</p>"
    )

    api_instance = _get_brevo_transactional_emails_api()
    if api_instance is None:
        return

    # Create the email data
    email_data = SendSmtpEmail(
        to=[{"email": user_registration.email}],
        subject=subject,
        html_content=html_content,
        sender={
            "name": "Samatwa Service Centre",
            "email": "samatwaservicecenter.gov.in@gmail.com",
        },
    )

    try:
        # Send the email
        api_response = api_instance.send_transac_email(email_data)
        print("Email sent successfully:", api_response)
    except ApiException as e:
        print("Exception when sending email: %s\n" % e)
