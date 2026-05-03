import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import PROCESSED_LABEL_NAME

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]


class GmailClient:
    def __init__(self):
        self.service = self._authenticate()
        self.processed_label_id = self._ensure_processed_label()

    def _authenticate(self):
        creds = None
        token_path = os.environ.get("GMAIL_TOKEN_PATH", "token.json")
        creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def _ensure_processed_label(self) -> str:
        result = self.service.users().labels().list(userId="me").execute()
        for label in result.get("labels", []):
            if label["name"] == PROCESSED_LABEL_NAME:
                return label["id"]

        new_label = (
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": PROCESSED_LABEL_NAME,
                    "labelListVisibility": "labelHide",
                    "messageListVisibility": "hide",
                },
            )
            .execute()
        )
        return new_label["id"]

    def search_threads(self, query: str, max_results: int = 10) -> dict:
        # Exclude threads already processed by this agent
        full_query = f"({query}) -label:{PROCESSED_LABEL_NAME}"
        result = (
            self.service.users()
            .threads()
            .list(userId="me", q=full_query, maxResults=max_results)
            .execute()
        )

        threads = []
        for thread in result.get("threads", []):
            thread_data = (
                self.service.users()
                .threads()
                .get(
                    userId="me",
                    id=thread["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Date"],
                )
                .execute()
            )
            messages = thread_data.get("messages", [])
            last_msg = messages[-1] if messages else {}
            headers = {
                h["name"]: h["value"]
                for h in last_msg.get("payload", {}).get("headers", [])
            }
            threads.append(
                {
                    "thread_id": thread["id"],
                    "snippet": thread_data.get("snippet", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "from": headers.get("From", ""),
                    "date": headers.get("Date", ""),
                    "message_count": len(messages),
                    "last_message_id": last_msg.get("id", ""),
                }
            )

        return {"threads": threads, "count": len(threads)}

    def get_thread(self, thread_id: str) -> dict:
        thread = (
            self.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        messages = []
        for msg in thread.get("messages", []):
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            messages.append(
                {
                    "message_id": msg["id"],
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "cc": headers.get("Cc", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "body": self._extract_body(msg["payload"]),
                }
            )

        return {"thread_id": thread_id, "messages": messages}

    def _extract_body(self, payload: dict) -> str:
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        if mime_type == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                # Return raw HTML; agent will read it as-is
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        if "parts" in payload:
            # Prefer plain text over HTML
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="replace"
                        )
            # Fall back to recursing into parts
            for part in payload["parts"]:
                body = self._extract_body(part)
                if body:
                    return body

        return ""

    def create_draft(
        self,
        thread_id: str,
        message_id: str,
        to: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> dict:
        if html_body:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
        else:
            msg = MIMEText(body, "plain")

        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        draft = (
            self.service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"raw": raw, "threadId": thread_id}},
            )
            .execute()
        )
        return {"draft_id": draft["id"], "status": "draft_created"}

    def mark_processed(self, thread_id: str) -> dict:
        self.service.users().threads().modify(
            userId="me",
            id=thread_id,
            body={"addLabelIds": [self.processed_label_id]},
        ).execute()
        return {"status": "marked_processed", "thread_id": thread_id}
