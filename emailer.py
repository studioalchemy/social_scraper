import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config
import report_doc

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
SUBJECT = "Analysis of ITC social scraper Agent"


def _gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID(),
        client_secret=config.GOOGLE_CLIENT_SECRET(),
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _docx_filename(report: dict) -> str:
    meta = report.get("_meta", {})
    brand = (report.get("header", {}) or {}).get("brand_name") or "Report"
    safe_brand = "".join(c if c.isalnum() else "_" for c in brand).strip("_") or "Report"
    date = meta.get("report_date", "").replace(",", "").replace(" ", "_") or "today"
    return f"{safe_brand}_Instagram_Analysis_{date}.docx"


def send_report(report: dict, subject: str | None = None) -> None:
    sender = config.GMAIL_SENDER_EMAIL()
    recipients = config.RECIPIENT_EMAILS()

    logger.info("Building DOCX report...")
    docx_bytes = report_doc.build_docx_bytes(report)
    filename = _docx_filename(report)

    body_text = (
        "Please find the latest Instagram competitive analysis attached.\n\n"
        "— ITC Social Scraper Agent"
    )

    msg = MIMEMultipart()
    msg["Subject"] = subject or SUBJECT
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_text, "plain"))

    attachment = MIMEApplication(
        docx_bytes,
        _subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    logger.info(f"Sending report to: {', '.join(recipients)} via Gmail API")
    service = _gmail_service()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info(f"Report sent successfully. Attachment: {filename} ({len(docx_bytes)} bytes)")
