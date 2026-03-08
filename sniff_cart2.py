#!/usr/bin/env python3
"""Navigates the store SPA, waits for items to fully render, screenshots it,
then clicks the first Add-to-Cart and captures the exact network request."""

import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright, Request

SESSION_FILE = Path(__file__).parent / "session.json"

def sniff():
    cart_reqs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()

        def on_request(req: Request):
            if "cart" in req.url.lower():
                print(f"\n→ REQUEST [{req.method}] {req.url}")
                print(f"  Headers: {dict(req.headers)}")
                try:
                    print(f"  Body: {req.post_data}")
                except:
                    pass
                cart_reqs.append({
                    "url": req.url,
                    "method": req.method,
                    "headers": dict(req.headers),
                    "body": req.post_data,
                })

        page.on("request", on_request)

        url = "https://store.bricklink.com/PremiumBrick#/shop?itemType=M&catID=67"
        print(f"Navigating to: {url}")
        page.goto(url, wait_until="domcontentloaded")

        # Wait for the React store to render items — look for price or item elements
        print("Waiting for items to render (up to 30s)...")
        try:
            page.wait_for_function(
                "document.querySelectorAll('[class*=\"item\"], [class*=\"product\"], [class*=\"lot\"]').length > 5",
                timeout=30_000,
            )
            print("Items detected!")
        except Exception as e:
            print(f"Wait timed out: {e}")

        # Take a screenshot to see the page state
        page.screenshot(path="store_screenshot.png", full_page=False)
        print("Screenshot saved to store_screenshot.png")

        # Log all visible text in buttons
        buttons = page.query_selector_all("button, a[class*='buy'], a[class*='cart'], [class*='buy'], [class*='cart']")
        print(f"\nFound {len(buttons)} cart/buy elements:")
        for b in buttons[:15]:
            try:
                txt = b.inner_text().strip()[:80]
                cls = (b.get_attribute("class") or "")[:60]
                print(f"  '{txt}' class='{cls}'")
            except:
                pass

        # Try to find and click a buy button
        buy_btn = None
        for sel in [
            "[class*='buy-btn']", "[class*='buyBtn']", "[class*='add-to-cart']",
            "[class*='addCart']", "button:has-text('Buy')", "button:has-text('Add')",
            "a:has-text('Buy')", "[data-action='addToCart']",
        ]:
            el = page.query_selector(sel)
            if el:
                print(f"\nFound element with selector: {sel}")
                print(f"  text='{el.inner_text().strip()[:60]}'")
                buy_btn = el
                break

        if buy_btn:
            print("Clicking...")
            buy_btn.click()
            time.sleep(3)
        else:
            print("\nNo buy button found. Leaving browser open for 15s to inspect manually.")
            time.sleep(15)

        Path("cart_reqs.json").write_text(json.dumps(cart_reqs, indent=2))
        browser.close()
        print(f"\nCaptured {len(cart_reqs)} cart requests → cart_reqs.json")

sniff()
