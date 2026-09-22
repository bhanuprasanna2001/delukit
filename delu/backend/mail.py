import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "delu@localhost")


def send_verify(email: str, link: str) -> None:
    if not SMTP_HOST:
        print(f"verify {email}: {link}", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"] = "Confirm your DELU account"
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content(f"Confirm your account by opening this link:\n\n{link}\n")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)
