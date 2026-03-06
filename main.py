"""
Google Workspace 週次レポート生成スクリプト。

処理フロー:
1. Google Calendar / Gmail / Drive から過去7日間のデータを取得
2. Vertex AI (Gemini) で要約
3. Gmail に下書きとして保存
"""

import os
import base64
import json
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.readonly",
]

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.0-flash")


# ─── 認証 ────────────────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open("token.json", "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("token.json が見つかりません。先に auth.py を実行してください。")
    return creds


# ─── Google Calendar ─────────────────────────────────────────────────────────

def fetch_calendar_events(service) -> list[dict]:
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=7)).isoformat()
    time_max = now.isoformat()

    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    events = []
    for e in result.get("items", []):
        start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
        events.append({
            "title": e.get("summary", "(無題)"),
            "start": start,
            "description": e.get("description", ""),
        })
    return events


# ─── Gmail ───────────────────────────────────────────────────────────────────

def fetch_gmail_messages(service, max_results: int = 20) -> list[dict]:
    query = "is:important newer_than:7d"
    list_result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = []
    for msg_ref in list_result.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "(件名なし)")
        sender = headers.get("From", "")
        snippet = msg.get("snippet", "")

        messages.append({
            "subject": subject,
            "from": sender,
            "snippet": snippet,
        })
    return messages


# ─── Google Drive ─────────────────────────────────────────────────────────────

def fetch_drive_files(service, max_results: int = 20) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f"modifiedTime > '{since}' and trashed = false"

    result = service.files().list(
        q=query,
        orderBy="modifiedTime desc",
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
    ).execute()

    files = []
    for f in result.get("files", []):
        files.append({
            "name": f.get("name", ""),
            "mimeType": f.get("mimeType", ""),
            "modifiedTime": f.get("modifiedTime", ""),
            "url": f.get("webViewLink", ""),
        })
    return files


# ─── Vertex AI (Gemini) ───────────────────────────────────────────────────────

def summarize_with_gemini(calendar_events: list, gmail_messages: list, drive_files: list) -> str:
    vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION)
    model = GenerativeModel(GEMINI_MODEL)

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""
あなたは優秀なアシスタントです。以下のGoogle Workspaceのデータをもとに、
過去7日間（〜{today}）の週次レポートを日本語でまとめてください。

## カレンダーイベント（{len(calendar_events)}件）
{json.dumps(calendar_events, ensure_ascii=False, indent=2)}

## 重要メール（{len(gmail_messages)}件）
{json.dumps(gmail_messages, ensure_ascii=False, indent=2)}

## 更新されたDriveファイル（{len(drive_files)}件）
{json.dumps(drive_files, ensure_ascii=False, indent=2)}

---
以下の構成で週次レポートを作成してください：

# 週次レポート {today}

## 今週のハイライト
（最も重要な出来事を3〜5点、箇条書き）

## カレンダー振り返り
（参加したミーティング・イベントの要約）

## 重要メール
（対応が必要そうなメールや重要な連絡事項）

## ファイル作業
（更新・作成されたファイルの概要）

## 来週に向けて
（今週の内容から読み取れるToDoや注意点）
"""

    response = model.generate_content(prompt)
    return response.text


# ─── Gmail 下書き作成 ─────────────────────────────────────────────────────────

def create_gmail_draft(service, subject: str, body: str) -> str:
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = "me"
    message["subject"] = subject

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": encoded}},
    ).execute()
    return draft["id"]


# ─── メイン ───────────────────────────────────────────────────────────────────

def main():
    print("認証中...")
    creds = get_credentials()

    calendar_service = build("calendar", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    print("カレンダーイベント取得中...")
    events = fetch_calendar_events(calendar_service)
    print(f"  {len(events)} 件取得")

    print("Gmail メッセージ取得中...")
    messages = fetch_gmail_messages(gmail_service)
    print(f"  {len(messages)} 件取得")

    print("Drive ファイル取得中...")
    files = fetch_drive_files(drive_service)
    print(f"  {len(files)} 件取得")

    print("Gemini で要約生成中...")
    summary = summarize_with_gemini(events, messages, files)

    today = datetime.now().strftime("%Y/%m/%d")
    subject = f"【週次レポート】{today}"

    print("Gmail 下書きを作成中...")
    draft_id = create_gmail_draft(gmail_service, subject, summary)
    print(f"完了！下書き ID: {draft_id}")
    print("Gmailの下書きを確認してください。")


if __name__ == "__main__":
    main()
