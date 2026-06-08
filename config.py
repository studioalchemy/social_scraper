import os
from dotenv import load_dotenv

load_dotenv()


def get_required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return value


APIFY_API_TOKEN = lambda: get_required("APIFY_API_TOKEN")
ANTHROPIC_API_KEY = lambda: get_required("ANTHROPIC_API_KEY")

# Gmail API (OAuth) — replaced SMTP because Railway blocks outbound SMTP.
GMAIL_SENDER_EMAIL = lambda: get_required("GMAIL_SENDER_EMAIL")
GOOGLE_CLIENT_ID = lambda: get_required("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = lambda: get_required("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = lambda: get_required("GOOGLE_REFRESH_TOKEN")

RECIPIENT_EMAILS = lambda: [
    e.strip() for e in get_required("RECIPIENT_EMAILS").split(",") if e.strip()
]

INSTAGRAM_ACCOUNTS = lambda: [
    a.strip().lstrip("@").lower()
    for a in get_required("INSTAGRAM_ACCOUNTS").split(",")
    if a.strip()
]

SCHEDULE_DAYS = lambda: int(os.getenv("SCHEDULE_DAYS", "7"))
