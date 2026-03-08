#!/usr/bin/env python3
"""
Sniffs the API calls that the Bricklink store SPA makes when loading inventory.
Run this first to discover the correct API endpoints and response structure.

Usage:
  python sniff_api.py <store_name>
"""

import sys
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "session.json"
OUT_FILE = Path(__file__).parent / "api_calls.json"

def sniff(store_name: str):
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page = context.new_page()

        def on_response(response):
            url = response.url
            # Capture all JSON responses from bricklink hosts
            if any(h in url for h in ["api.bricklink.com", "store.bricklink.com", "www.bricklink.com"]):
                if ".ajax" in url or "/api/" in url or "ajax" in url.lower():
                    try:
                        body = response.json()
                        captured.append({"url": url, "status": response.status, "body": body})
                        print(f"  [{response.status}] {url}")
                    except Exception:
                        pass

        page.on("response", on_response)

        url = f"https://store.bricklink.com/{store_name}#/shop?catType=M"
        print(f"Loading: {url}")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(8)  # let React finish rendering and all API calls complete

        # Scroll to trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)

        browser.close()

    OUT_FILE.write_text(json.dumps(captured, indent=2))
    print(f"\nCaptured {len(captured)} API calls → {OUT_FILE}")
    for entry in captured:
        print(f"\n{'─'*60}")
        print(f"URL: {entry['url']}")
        body = entry['body']
        if isinstance(body, dict):
            print(f"Keys: {list(body.keys())}")
        elif isinstance(body, list):
            print(f"Array of {len(body)} items, first: {json.dumps(body[0], indent=2)[:300] if body else '[]'}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sniff(sys.argv[1])
