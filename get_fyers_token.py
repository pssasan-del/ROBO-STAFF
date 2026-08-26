"""FYERS API v3 access-token helper for local use.

Usage:
  1) Put FYERS_CLIENT_ID, FYERS_SECRET_KEY and FYERS_REDIRECT_URI in .env
  2) pip install -r requirements.txt
  3) python get_fyers_token.py

The script opens the FYERS authorization page, listens for the localhost
callback when possible, exchanges the auth_code for an access token, and
prints the token so you can copy it into your hosting environment.

It never writes the access token to source code or commits it anywhere.
"""

from __future__ import annotations

import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "").strip()
SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "").strip()
REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "").strip()


def fail(message: str) -> None:
    print(f"\nERROR: {message}\n")
    sys.exit(1)


if not CLIENT_ID:
    fail("FYERS_CLIENT_ID is missing in .env")
if not SECRET_KEY:
    fail("FYERS_SECRET_KEY is missing in .env")
if not REDIRECT_URI:
    fail("FYERS_REDIRECT_URI is missing in .env")

try:
    from fyers_apiv3 import fyersModel
except ImportError:
    fail("fyers-apiv3 is not installed. Run: pip install -r requirements.txt")


session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code",
)

try:
    auth_url = session.generate_authcode()
except Exception as exc:
    fail(f"Could not create FYERS authorization URL: {exc}")

captured = {"auth_code": None, "error": None}
server = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        captured["auth_code"] = (params.get("auth_code") or [None])[0]
        captured["error"] = (params.get("error") or [None])[0]

        body = (
            "<html><body style='font-family:Arial;padding:40px'>"
            "<h2>FYERS authorization received.</h2>"
            "<p>You can close this browser tab and return to the terminal.</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def start_callback_server():
    global server
    parsed = urlparse(REDIRECT_URI)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False
    port = parsed.port or 80
    try:
        server = HTTPServer((parsed.hostname, port), CallbackHandler)
        Thread(target=server.handle_request, daemon=True).start()
        return True
    except OSError as exc:
        print(f"Local callback listener could not start: {exc}")
        return False


listener_started = start_callback_server()

print("\nFYERS Access Token Generator")
print("--------------------------------")
print(f"Client ID   : {CLIENT_ID[:4]}...{CLIENT_ID[-4:] if len(CLIENT_ID) > 8 else ''}")
print(f"Redirect URI: {REDIRECT_URI}")
print("\nOpening FYERS login/authorization page in your browser...")

try:
    webbrowser.open(auth_url)
except Exception:
    pass

print("\nIf the browser does not open, copy this URL into Chrome:\n")
print(auth_url)

if listener_started:
    print("\nWaiting up to 180 seconds for the localhost callback...")
    deadline = time.time() + 180
    while time.time() < deadline and not captured["auth_code"] and not captured["error"]:
        time.sleep(0.5)

    if server:
        try:
            server.server_close()
        except Exception:
            pass

if captured["error"]:
    fail(f"FYERS authorization returned an error: {captured['error']}")

auth_code = captured["auth_code"]

if not auth_code:
    print("\nAutomatic callback capture did not complete.")
    print("After FYERS login, copy the FULL callback URL from the browser address bar.")
    callback_url = input("Paste callback URL (or auth_code directly): ").strip()
    if "auth_code=" in callback_url:
        auth_code = (parse_qs(urlparse(callback_url).query).get("auth_code") or [None])[0]
    else:
        auth_code = callback_url

if not auth_code:
    fail("No auth_code was received.")

try:
    session.set_token(auth_code)
    token_response = session.generate_token()
except Exception as exc:
    fail(f"Token exchange failed: {exc}")

if not isinstance(token_response, dict):
    fail(f"Unexpected FYERS token response: {token_response!r}")

access_token = token_response.get("access_token")
if not access_token:
    message = token_response.get("message") or token_response.get("msg") or token_response
    fail(f"FYERS did not return an access token: {message}")

print("\nSUCCESS: FYERS access token generated.\n")
print("Copy the value below into Render as FYERS_ACCESS_TOKEN:\n")
print(access_token)
print("\nSecurity: do not paste this token into GitHub, screenshots, or chat messages.")
