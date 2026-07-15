#!/usr/bin/env python3
"""
Import a browser cookie export into session.json for BricklinkHelper.

Use this when the automated login browser (--save-session) can't run
reliably in this environment. Instead:

  1. Log into https://www.bricklink.com in your regular, everyday browser.
  2. Install a cookie-export extension (e.g. "Cookie-Editor" for Chrome
     or Firefox).
  3. On a bricklink.com page, open the extension and Export > Export as JSON.
  4. Save that JSON to a file.
  5. Run:
       venv/bin/python import_session.py <exported_cookies.json>

This writes session.json in the format bulk_order.py expects.
"""

import sys
import json
from pathlib import Path

SESSION_FILE = Path(__file__).parent / "session.json"

SAME_SITE_MAP = {
    "no_restriction": "None",
    "unspecified": "Lax",
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
}


def convert_cookie(raw: dict) -> dict:
    same_site_raw = str(raw.get("sameSite", "lax")).lower()
    expires = raw.get("expirationDate", raw.get("expires", raw.get("expiry", -1)))
    if expires is None:
        expires = -1
    return {
        "name": raw["name"],
        "value": raw["value"],
        "domain": raw["domain"],
        "path": raw.get("path", "/"),
        "expires": float(expires),
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": bool(raw.get("secure", False)),
        "sameSite": SAME_SITE_MAP.get(same_site_raw, "Lax"),
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: venv/bin/python import_session.py <exported_cookies.json>")
        sys.exit(1)

    src = Path(sys.argv[1])
    raw_cookies = json.loads(src.read_text())
    if isinstance(raw_cookies, dict) and "cookies" in raw_cookies:
        raw_cookies = raw_cookies["cookies"]  # already a storage_state-style file

    bricklink_cookies = [
        convert_cookie(c) for c in raw_cookies if "bricklink.com" in c.get("domain", "")
    ]

    if not bricklink_cookies:
        print(
            "No bricklink.com cookies found in the export. "
            "Make sure you're logged in and exported from a bricklink.com page."
        )
        sys.exit(1)

    session_state = {"cookies": bricklink_cookies, "origins": []}
    SESSION_FILE.write_text(json.dumps(session_state, indent=2))
    print(f"Imported {len(bricklink_cookies)} bricklink.com cookie(s) to {SESSION_FILE}")


if __name__ == "__main__":
    main()
