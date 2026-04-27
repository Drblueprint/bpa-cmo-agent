"""
Poll the CMO Agent Google Chat space for new messages.

Tracks a cursor in ./gchat_state.json so each run only surfaces messages
that arrived after the previous run.

Usage:
  python3 gchat_poller.py              # show new messages since last poll
  python3 gchat_poller.py --space NAME # target a specific space (spaces/XXXX)
  python3 gchat_poller.py --reset      # reset cursor to "now"
  python3 gchat_poller.py --since-hours 24  # one-shot look-back
  python3 gchat_poller.py --list-spaces
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE = Path(__file__).parent
TOKEN_PATH = BASE / "gchat_token.json"
STATE_PATH = BASE / "gchat_state.json"
SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
]

# Kurt/Toby's actual sender IDs will populate on first poll \u2014 we just show
# displayName directly. This dict is a spot for aliases if we want them later.
SENDER_ALIASES: dict = {}


def load_creds() -> Credentials:
    if not TOKEN_PATH.exists():
        raise SystemExit(
            f"No token at {TOKEN_PATH}. Run gchat_auth.py first."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def list_spaces(svc) -> list:
    out = []
    page = None
    while True:
        resp = svc.spaces().list(pageSize=100, pageToken=page).execute()
        out.extend(resp.get("spaces", []))
        page = resp.get("nextPageToken")
        if not page:
            break
    return out


def resolve_cmo_space(svc, preferred) -> str:
    spaces = list_spaces(svc)
    if preferred:
        for s in spaces:
            if s["name"] == preferred or s.get("displayName") == preferred:
                return s["name"]
        raise SystemExit(f"Space {preferred} not found.")
    # Default: prefer displayName match on "CMO"
    for s in spaces:
        dn = (s.get("displayName") or "").lower()
        if "cmo" in dn:
            return s["name"]
    raise SystemExit(
        "No space with 'CMO' in its name. Run with --list-spaces to see options."
    )


def fetch_messages(svc, space_name: str, since_iso: str) -> list:
    """Pull messages created after since_iso. Handles pagination."""
    out = []
    page = None
    # createTime filter uses RFC 3339 timestamps
    flt = f'createTime > "{since_iso}"'
    while True:
        resp = (
            svc.spaces()
            .messages()
            .list(
                parent=space_name,
                pageSize=100,
                pageToken=page,
                filter=flt,
                orderBy="createTime ASC",
            )
            .execute()
        )
        out.extend(resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page:
            break
    return out


def format_message(m: dict) -> dict:
    sender = m.get("sender", {}) or {}
    sender_id = sender.get("name", "")
    display = SENDER_ALIASES.get(sender_id, sender_id.split("/")[-1])
    # For human senders we'd ideally resolve displayName, but the Chat API
    # doesn't return it on messages.list without extra lookup. First pass we
    # show the raw sender id; we can layer on a resolver later.
    return {
        "id": m.get("name"),
        "createTime": m.get("createTime"),
        "sender": display,
        "sender_type": sender.get("type", "HUMAN"),
        "text": m.get("text", ""),
        "thread": (m.get("thread") or {}).get("name", ""),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--space", help="Space name (spaces/XXXX) or displayName")
    p.add_argument("--reset", action="store_true",
                   help="Reset cursor to now; next run starts from future messages")
    p.add_argument("--since-hours", type=int,
                   help="One-shot: look back N hours instead of using stored cursor")
    p.add_argument("--list-spaces", action="store_true")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of human-readable")
    args = p.parse_args()

    creds = load_creds()
    svc = build("chat", "v1", credentials=creds)

    if args.list_spaces:
        for s in list_spaces(svc):
            dn = s.get("displayName") or "(direct message)"
            print(f"{s['name']}  \u2014  {dn}  [{s.get('spaceType', '?')}]")
        return

    space = resolve_cmo_space(svc, args.space)
    state = load_state()

    if args.reset:
        state[space] = iso_now()
        save_state(state)
        print(f"Cursor reset for {space} to {state[space]}")
        return

    if args.since_hours:
        since = (datetime.now(timezone.utc) - timedelta(hours=args.since_hours)).isoformat(timespec="seconds").replace("+00:00", "Z")
    else:
        since = state.get(space) or (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(timespec="seconds").replace("+00:00", "Z")

    messages = fetch_messages(svc, space, since)
    formatted = [format_message(m) for m in messages]

    if args.json:
        print(json.dumps({"space": space, "since": since, "messages": formatted}, indent=2))
    else:
        print(f"Space: {space}")
        print(f"Since: {since}")
        print(f"New messages: {len(formatted)}")
        for m in formatted:
            preview = (m["text"][:240] + "\u2026") if len(m["text"]) > 240 else m["text"]
            print(f"\n[{m['createTime']}] {m['sender']}")
            print(preview)

    # Advance cursor only if NOT a one-shot look-back
    if not args.since_hours and messages:
        latest = max(m["createTime"] for m in messages)
        state[space] = latest
        save_state(state)


if __name__ == "__main__":
    main()
