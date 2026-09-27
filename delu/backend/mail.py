import json
import os
import smtplib
import urllib.request
from contextlib import suppress
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "delu@localhost")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", SMTP_FROM)
CONTACT_TO = os.getenv("CONTACT_TO", "bhanu.prasanna2001@gmail.com")
REQUIRE_MAIL = os.getenv("DELU_REQUIRE_MAIL", "0") == "1"


def configured() -> bool:
    return bool(RESEND_API_KEY or (SMTP_HOST and SMTP_USER and SMTP_PASS))


def _via_resend(to: str, subject: str, text: str, reply_to: str = "") -> bool:
    if not RESEND_API_KEY:
        return False
    payload: dict = {
        "from": RESEND_FROM,
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        return 200 <= res.status < 300


def _via_smtp(to: str, subject: str, text: str, reply_to: str = "") -> bool:
    if not SMTP_HOST:
        return False
    password = SMTP_PASS or RESEND_API_KEY
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, password)
        smtp.send_message(msg)
    return True


def _deliver(to: str, subject: str, text: str, reply_to: str = "") -> bool:
    with suppress(Exception):
        if _via_resend(to, subject, text, reply_to):
            return True
    with suppress(Exception):
        if _via_smtp(to, subject, text, reply_to):
            return True
    return False


def send_verify(email: str, link: str) -> None:
    body = (
        "Confirm your DELU account by opening this link:\n\n"
        f"{link}\n\nThe link expires in 24 hours. "
        "If you did not sign up, ignore this email."
    )
    if not _deliver(email, "Confirm your DELU account", body):
        if REQUIRE_MAIL:
            raise RuntimeError("Verification email could not be delivered")
        print(f"verify {email}: {link}", flush=True)


def send_contact(name: str, sender: str, topic: str, message: str) -> bool:
    body = f"From: {name} <{sender}>\nTopic: {topic}\n\n{message}\n"
    ok = _deliver(CONTACT_TO, f"[DELU contact: {topic}] {name}", body, sender)
    if not ok and not REQUIRE_MAIL:
        print(f"contact {sender} [{topic}]: {message}", flush=True)
    return ok
