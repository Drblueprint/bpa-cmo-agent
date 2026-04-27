"""
One-time Google Chat OAuth flow for the BPA CMO Agent.

Prereqs:
  1. Google Cloud project with Google Chat API enabled
  2. OAuth 2.0 Client ID (application type: Desktop app)
  3. Downloaded credentials JSON saved at ./gchat_oauth.json

Run once:
  python3 gchat_auth.py

Opens a browser, asks for consent, then stores the refresh token at
./gchat_token.json for gchat_poller.py to use.
"""
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BASE = Path(__file__).parent
OAUTH_CLIENT_PATH = BASE / "gchat_oauth.json"
TOKEN_PATH = BASE / "gchat_token.json"

# Minimum scopes for reading Kurt/Toby messages in the CMO space.
# chat.messages.readonly = read messages in spaces the user is a member of
# chat.spaces.readonly   = list spaces + members (to resolve sender names)
SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
]


def authorize() -> Credentials:
    if not OAUTH_CLIENT_PATH.exists():
        raise SystemExit(
            f"Missing {OAUTH_CLIENT_PATH}\n"
            "Download the OAuth Desktop client JSON from Google Cloud Console "
            "and save it to that path."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), SCOPES
    )
    # Opens the local browser, binds a short-lived loopback server to catch
    # the OAuth redirect, hands back Credentials with a refresh_token.
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message=(
            "Opening browser for Google Chat authorization.\n"
            "Grant read access to the CMO space so the agent can follow conversations.\n"
        ),
        success_message="Authorization complete. You can close this browser tab.",
    )

    TOKEN_PATH.write_text(creds.to_json())
    print(f"Token saved to {TOKEN_PATH}")
    return creds


def sanity_check(creds: Credentials) -> None:
    """Confirm the token works by listing the spaces the user is a member of."""
    svc = build("chat", "v1", credentials=creds)
    resp = svc.spaces().list(pageSize=50).execute()
    spaces = resp.get("spaces", [])
    print(f"\nVisible spaces ({len(spaces)}):")
    for s in spaces:
        name = s.get("displayName") or "(direct message)"
        print(f"  {s['name']}  \u2014  {name}  [{s.get('spaceType', '?')}]")


if __name__ == "__main__":
    creds = authorize()
    sanity_check(creds)
