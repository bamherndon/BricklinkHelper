#!/usr/bin/env python3
"""
Bricklink Minifig Bulk Orderer

Calls the Bricklink store API directly using a saved browser session.
Pricing rules:
  - Town minifigs (category 67):  $3.00 or less → add to cart
  - All other minifigs:           $5.00 or less → add to cart

Usage:
  python bulk_order.py --save-session               Log in once, save browser session
  python bulk_order.py <store_name>                 Dry run — show what would be added
  python bulk_order.py <store_name> --buy           Add qualifying items to cart
"""

import sys
import re
import json
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# ── Config ────────────────────────────────────────────────────────────────────

SESSION_FILE = Path(__file__).parent / "session.json"

TOWN_CAT_ID    = 67       # Bricklink minifig category ID for "Town"
TOWN_MAX_PRICE = 3.00
DEFAULT_MAX_PRICE = 5.00

PAGE_SIZE   = 200         # Items per API page (Bricklink max appears to be 500)
DELAY       = 0.4         # Seconds between cart-add calls — be polite

# ── Session ───────────────────────────────────────────────────────────────────

def save_session():
    """Open a headed browser, wait for the user to log in, save cookies."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.bricklink.com/login.asp")
        print("Log in to Bricklink in the browser window.")
        print("Waiting for login (watching for Sign Out link)...")
        page.wait_for_selector(
            "a[href*='logout'], a[href*='signOut'], a:has-text('Sign Out'), a:has-text('Log Out')",
            timeout=300_000,
        )
        print("Login detected — saving session...")
        context.storage_state(path=str(SESSION_FILE))
        browser.close()
    print(f"Session saved to {SESSION_FILE}")


def load_cookies() -> dict[str, str]:
    """Return a flat name→value dict of cookies from the saved session."""
    session = json.loads(SESSION_FILE.read_text())
    return {c["name"]: c["value"] for c in session.get("cookies", [])}


def make_session(cookies: dict) -> requests.Session:
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0",
        "Accept":          "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://store.bricklink.com/",
        "Origin":          "https://store.bricklink.com",
        "X-Requested-With": "XMLHttpRequest",
    })
    return s

# ── Store ID lookup ───────────────────────────────────────────────────────────

def get_store_sid(store_name: str) -> str:
    """
    Resolve the numeric store ID (sid) for a store username.
    We open the store page briefly and capture the sid from the first API call.
    """
    captured = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page = context.new_page()

        def on_response(resp):
            m = re.search(r"[?&]sid=(\d+)", resp.url)
            if m and not captured:
                captured.append(m.group(1))

        page.on("response", on_response)
        page.goto(f"https://store.bricklink.com/{store_name}",
                  wait_until="domcontentloaded")
        # Wait until we capture a sid, up to 15 s
        for _ in range(30):
            if captured:
                break
            time.sleep(0.5)
        browser.close()

    if not captured:
        raise RuntimeError(
            f"Could not determine store ID for '{store_name}'. "
            "Check the store name and that you are logged in."
        )
    return captured[0]

# ── Inventory fetch ───────────────────────────────────────────────────────────

def fetch_all_minifigs(sid: str, http: requests.Session) -> tuple[list[dict], dict[int, str]]:
    """
    Paginate through the store's minifig inventory.
    Returns (items, cat_map) where cat_map is {category_id: category_name}.
    """
    all_items: list[dict] = []
    cat_map: dict[int, str] = {}
    page = 1

    while True:
        resp = http.get(
            "https://store.bricklink.com/ajax/clone/store/searchitems.ajax",
            params={
                "sid":      sid,
                "itemType": "M",    # Minifigures only
                "pgSize":   PAGE_SIZE,
                "pg":       page,
                "sort":     "0",
                "desc":     "0",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("returnCode") != 0:
            raise RuntimeError(f"API error: {data.get('returnMessage')}")

        result = data["result"]

        # Build category map from the first page response
        if page == 1:
            for cat_group in result.get("categories", []):
                for c in cat_group.get("categories", []):
                    cat_map[c["id"]] = c["name"]

        # With itemType=M filter the API returns one group with no itemType key
        page_items: list[dict] = []
        groups = result.get("groups", [])
        group_total = groups[0]["total"] if groups else 0

        for group in groups:
            page_items.extend(group.get("items", []))

        all_items.extend(page_items)
        fetched = len(all_items)
        print(f"  Page {page}: {len(page_items)} items  ({fetched}/{group_total} total)")

        if fetched >= group_total or not page_items:
            break
        page += 1
        time.sleep(DELAY)

    return all_items, cat_map

# ── Pricing logic ─────────────────────────────────────────────────────────────

def top_cat_id(item: dict) -> int:
    cat_str = item.get("categoryString", "")
    try:
        return int(cat_str.split(".")[0])
    except (ValueError, IndexError):
        return 0


def max_allowed_price(item: dict) -> float:
    return TOWN_MAX_PRICE if top_cat_id(item) == TOWN_CAT_ID else DEFAULT_MAX_PRICE


def qualifies(item: dict) -> bool:
    price = item.get("rawConvertedPrice", float("inf"))
    return price <= max_allowed_price(item)

# ── Cart ──────────────────────────────────────────────────────────────────────

def add_to_cart(inv_id: str | int, sid: str, http: requests.Session) -> bool:
    """POST an add-to-cart request. Returns True on success."""
    item_array = json.dumps([{
        "invID":      int(inv_id),
        "invQty":     "1",
        "sellerID":   int(sid),
        "sourceType": 1,
    }])
    resp = http.post(
        "https://store.bricklink.com/ajax/clone/cart/add.ajax",
        data={
            "itemArray":   item_array,
            "sid":         sid,
            "srcLocation": "1100",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    if not resp.ok:
        return False
    result = resp.json()
    return result.get("returnCode") == 0

# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(items: list[dict], cat_map: dict[int, str], label: str = "Order"):
    """Print a table of Theme | Count | Total Price, sorted by count desc."""
    from collections import defaultdict

    theme_count: dict[str, int]   = defaultdict(int)
    theme_price: dict[str, float] = defaultdict(float)

    for item in items:
        cat_id = top_cat_id(item)
        name   = cat_map.get(cat_id, f"Category {cat_id}" if cat_id else "Unknown")
        theme_count[name] += 1
        theme_price[name] += item.get("rawConvertedPrice", 0.0)

    # Sort by count descending, then name
    rows = sorted(theme_count.items(), key=lambda x: (-x[1], x[0]))

    col_theme = max((len(t) for t in theme_count), default=5)
    col_theme = max(col_theme, 5)

    total_figs  = sum(theme_count.values())
    total_price = sum(theme_price.values())

    print(f"\n{'═'*60}")
    print(f"  {label} Summary")
    print(f"{'═'*60}")
    print(f"  {'THEME':<{col_theme}}  {'FIGS':>5}  {'TOTAL':>8}")
    print(f"  {'─'*col_theme}  {'─'*5}  {'─'*8}")
    for theme, count in rows:
        price = theme_price[theme]
        print(f"  {theme:<{col_theme}}  {count:>5}  ${price:>7.2f}")
    print(f"  {'─'*col_theme}  {'─'*5}  {'─'*8}")
    print(f"  {'TOTAL':<{col_theme}}  {total_figs:>5}  ${total_price:>7.2f}")
    print(f"{'═'*60}")


# ── Theme grouping ────────────────────────────────────────────────────────────

def group_by_theme(items: list[dict], cat_map: dict[int, str]) -> list[tuple[str, list[dict]]]:
    """Return [(theme_name, [items])] sorted by count descending."""
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        cat_id = top_cat_id(item)
        name   = cat_map.get(cat_id, f"Category {cat_id}" if cat_id else "Unknown")
        groups[name].append(item)
    return sorted(groups.items(), key=lambda x: (-len(x[1]), x[0]))


def print_theme_items(theme: str, items: list[dict]):
    """Print a per-theme item list with prices."""
    total = sum(i.get("rawConvertedPrice", 0) for i in items)
    print(f"\n  Theme : {theme}")
    print(f"  Figs  : {len(items)}   Total: ${total:.2f}")
    print(f"  {'─'*58}")
    for item in items:
        pr   = item.get("rawConvertedPrice", 0)
        lim  = max_allowed_price(item)
        name = item.get("itemName", "?")[:55]
        print(f"    ${pr:>5.2f} / ${lim:.2f}  {name}")


# ── Main flow ─────────────────────────────────────────────────────────────────

def process_store(store_name: str, dry_run: bool):
    if not SESSION_FILE.exists():
        print("No session file found. Run  python bulk_order.py --save-session  first.")
        sys.exit(1)

    cookies = load_cookies()
    http    = make_session(cookies)

    # 1. Resolve store ID
    print(f"Resolving store ID for '{store_name}'...")
    sid = get_store_sid(store_name)
    print(f"  sid = {sid}\n")

    # 2. Fetch all minifigs
    print("Fetching minifig inventory...")
    items, cat_map = fetch_all_minifigs(sid, http)
    print(f"  {len(items)} minifig lots found\n")

    # 3. Split into qualifying / skipped
    qualifying = [i for i in items if qualifies(i)]
    skipped    = [i for i in items if not qualifies(i)]

    mode_tag = "[DRY RUN] " if dry_run else ""
    print(f"{mode_tag}Qualifying items : {len(qualifying)}")
    print(f"Skipped (price)  : {len(skipped)}")

    if not qualifying:
        print("\nNothing to add.")
        return

    themes = group_by_theme(qualifying, cat_map)

    if dry_run:
        for theme, theme_items in themes:
            print_theme_items(theme, theme_items)
        print_summary(qualifying, cat_map, label="Dry Run — Would Order")
        print(f"\nUse --buy to actually add {len(qualifying)} items to cart.")
        return

    # 4. Interactive per-theme buy
    confirmed: list[dict] = []
    skipped_themes: list[str] = []

    print(f"\nReviewing {len(themes)} theme(s) interactively.\n")

    for theme, theme_items in themes:
        print_theme_items(theme, theme_items)
        try:
            answer = input(f"\n  Buy these {len(theme_items)} fig(s) from '{theme}'? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            break
        if answer == "y":
            confirmed.extend(theme_items)
            print(f"  ✓ Added {len(theme_items)} fig(s) to purchase list.")
        else:
            skipped_themes.append(theme)
            print(f"  – Skipped.")

    if not confirmed:
        print("\nNothing selected. Exiting.")
        return

    total_confirmed = sum(i.get("rawConvertedPrice", 0) for i in confirmed)
    print(f"\nAdding {len(confirmed)} item(s) (${total_confirmed:.2f}) to cart...")

    # 5. Add to cart
    added_items: list[dict] = []
    failed:      list[dict] = []

    for item in confirmed:
        inv_id = item.get("invID", "")
        name   = item.get("itemName", "?")[:50]
        ok = add_to_cart(inv_id, sid, http)
        if ok:
            added_items.append(item)
            print(f"  + {name}")
        else:
            failed.append(item)
            print(f"  ! FAILED: {name}")
        time.sleep(DELAY)

    print_summary(added_items, cat_map, label="Order")

    if skipped_themes:
        print(f"\n  Skipped themes: {', '.join(skipped_themes)}")

    if failed:
        print(f"\n  {len(failed)} failed item(s):")
        for item in failed:
            print(f"    - {item.get('itemName','?')} (invID={item.get('invID')})")

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if args[0] == "--save-session":
        save_session()
        return

    store_name = args[0]
    dry_run    = "--buy" not in args
    process_store(store_name, dry_run)


if __name__ == "__main__":
    main()
