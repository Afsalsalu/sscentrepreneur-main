import os
import smtplib
from dotenv import load_dotenv

load_dotenv()

def test_smtp_connection():
    try:
        username = os.getenv("SMTP_USERNAME", "")
        password = os.getenv("SMTP_PASSWORD", "")
        if not username or not password:
            print("SMTP credentials are not configured.")
            return
        server = smtplib.SMTP(
            os.getenv("SMTP_HOST", "smtp-relay.brevo.com"),
            int(os.getenv("SMTP_PORT", "587")),
        )
        server.ehlo()
        server.starttls()
        server.login(username, password)
        print("SMTP connection successful")
        server.quit()
    except Exception as e:
        print(f"SMTP connection error: {e}")

if __name__ == "__main__":
    test_smtp_connection()

