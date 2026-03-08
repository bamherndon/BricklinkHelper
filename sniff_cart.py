#!/usr/bin/env python3
"""
Navigates to a PremiumBrick minifig, clicks Add to Cart, and captures the API call.
"""
import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "session.json"

def sniff():
    cart_calls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page = context.new_page()

        def on_request(request):
            if "cart" in request.url.lower() and ".ajax" in request.url:
                print(f"  REQ [{request.method}] {request.url}")
                try:
                    print(f"       body: {request.post_data}")
                except:
                    pass

        def on_response(response):
            if "cart" in response.url.lower() and ".ajax" in response.url:
                try:
                    body = response.json()
                    cart_calls.append({"url": response.url, "body": body})
                    print(f"  RSP [{response.status}] {response.url}")
                    print(f"       {json.dumps(body)[:300]}")
                except:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        # Navigate to store — let React fully load
        url = "https://store.bricklink.com/PremiumBrick#/shop"
        print(f"Loading: {url}")
        page.goto(url, wait_until="domcontentloaded")

        # Wait for an item card to actually appear (up to 20s)
        print("Waiting for items to render...")
        try:
            page.wait_for_selector("[class*='item'], [class*='product'], [class*='lot'], [class*='inv']", timeout=20_000)
        except:
            pass
        time.sleep(3)

        # Dump all buttons and their text for inspection
        buttons = page.query_selector_all("button, input[type='submit'], input[type='button']")
        print(f"\nFound {len(buttons)} buttons:")
        for b in buttons[:20]:
            try:
                print(f"  btn: '{b.inner_text().strip()[:60] or b.get_attribute('value')}' class='{b.get_attribute('class') or ''}'")
            except:
                pass

        # Try various selectors for Add to Cart
        selectors = [
            "button:has-text('Add to Cart')",
            "button:has-text('Add')",
            "input[value*='Add']",
            "[class*='cart']",
            "[class*='Cart']",
            "[onclick*='cart']",
            "a:has-text('Add')",
        ]
        btn = None
        for sel in selectors:
            btn = page.query_selector(sel)
            if btn:
                print(f"\nFound button with selector: {sel}")
                break

        if btn:
            btn.click()
            time.sleep(3)
        else:
            print("\nNo Add to Cart button found. Saving page HTML for inspection.")
            Path("debug_cart_page.html").write_text(page.content())
            time.sleep(5)

        Path("cart_calls.json").write_text(json.dumps(cart_calls, indent=2))
        browser.close()

sniff()
