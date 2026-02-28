"""
One-time Gmail OAuth2 authorization script.

Run this ONCE from the project root to create gmail_token.json:
    python scripts/gmail_auth.py

Prerequisites:
1. Google Cloud project with Gmail API enabled
2. OAuth2 credentials downloaded as client_secret.json in the project root
3. Your Gmail address added to "Test users" on the OAuth consent screen

After running, gmail_token.json is saved and auto-refreshed by the app.
"""

from __future__ import annotations

import pathlib
import sys

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CREDENTIALS_FILE = "client_secret.json"
TOKEN_FILE = "gmail_token.json"


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib is not installed.")
        print("Run: pip install google-auth-oauthlib")
        sys.exit(1)

    creds_path = pathlib.Path(CREDENTIALS_FILE)
    if not creds_path.exists():
        print(f"ERROR: {CREDENTIALS_FILE} not found in the current directory.")
        print()
        print("Steps to get it:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create a project → APIs & Services → Enable APIs → Gmail API")
        print("  3. APIs & Services → Credentials → Create Credentials → OAuth client ID")
        print("     Application type: Desktop app")
        print("  4. Download the JSON and save it as client_secret.json here")
        print("  5. OAuth consent screen → Add your Gmail as a Test user")
        sys.exit(1)

    print("Opening browser for Gmail authorization...")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = pathlib.Path(TOKEN_FILE)
    token_path.write_text(creds.to_json())
    print(f"\nDone! Token saved to {TOKEN_FILE}")
    print("The app will auto-refresh this token when needed.")


if __name__ == "__main__":
    main()
