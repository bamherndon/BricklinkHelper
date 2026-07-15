#!/usr/bin/env python3
"""
BrickLink Category Wishlist Builder

Scrapes every minifig listed under a BrickLink catalog category
(https://www.bricklink.com/catalogList.asp?catType=M&catString=<id>)
and writes a Wanted List XML file for bulk upload at:
  https://www.bricklink.com/v2/wanted/upload.page

Usage:
  python category_wishlist.py <catString>

Example:
  python category_wishlist.py 768        # Super Heroes
"""

import sys
import re
import json
import time
import html
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

DELAY = 1.0  # seconds between page loads — be polite
DEFAULT_QTY = 2
DEFAULT_MAX_PRICE = 5.00

ITEM_RE = re.compile(
    r'catalogitem\.page\?M=([^"\']+)">\1</a>.*?<strong>(.*?)</strong>',
    re.S,
)


def clean_name(raw: str) -> str:
    no_tags = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(no_tags).strip()


def load_page(page, url: str) -> str:
    """Navigate to url, waiting out the AWS WAF JS challenge if it appears."""
    page.goto(url, wait_until="load", timeout=30000)
    content = page.content()
    if "challenge-container" in content:
        time.sleep(6)
        page.wait_for_load_state("networkidle", timeout=20000)
        content = page.content()
    return content


TOTAL_RE = re.compile(
    r"<b>(\d+)</b>\s*Items Found\.\s*Page\s*<b>\d+</b>\s*of\s*<b>(\d+)</b>"
)


def parse_totals(html_text: str) -> tuple[int, int]:
    """Returns (total_items, total_pages) from the 'N Items Found. Page X of Y' line."""
    m = TOTAL_RE.search(html_text)
    if not m:
        return (0, 1)
    return (int(m.group(1)), int(m.group(2)))


def parse_items(html_text: str) -> list[dict]:
    return [
        {"itemID": item_id, "name": clean_name(name)}
        for item_id, name in ITEM_RE.findall(html_text)
    ]


LAUNCH_ARGS = ["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0"


def new_browser(p):
    browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
    context = browser.new_context(user_agent=USER_AGENT)
    page = context.new_page()
    return browser, context, page


def load_page_with_retry(p, browser, context, page, url: str, attempts: int = 3):
    """Load url, relaunching the whole browser if the renderer crashes."""
    for attempt in range(1, attempts + 1):
        try:
            return browser, context, page, load_page(page, url)
        except Exception as e:
            print(f"    load failed (attempt {attempt}/{attempts}): {e}")
            try:
                browser.close()
            except Exception:
                pass
            time.sleep(2)
            browser, context, page = new_browser(p)
    raise RuntimeError(f"Giving up on {url} after {attempts} attempts")


def scrape_category(cat_string: str) -> list[dict]:
    all_items: list[dict] = []
    seen: set[str] = set()

    with sync_playwright() as p:
        browser, context, page = new_browser(p)

        first_url = f"https://www.bricklink.com/catalogList.asp?v=0&pg=1&catString={cat_string}&catType=M"
        print("  Fetching page 1...")
        browser, context, page, first_html = load_page_with_retry(p, browser, context, page, first_url)
        total_items, total_pages = parse_totals(first_html)
        print(f"  {total_items} items found across {total_pages} page(s)")

        for pg, html_text in enumerate(
            [first_html] + [None] * (total_pages - 1), start=1
        ):
            if html_text is None:
                url = f"https://www.bricklink.com/catalogList.asp?v=0&pg={pg}&catString={cat_string}&catType=M"
                print(f"  Fetching page {pg}...")
                browser, context, page, html_text = load_page_with_retry(p, browser, context, page, url)
                time.sleep(DELAY)

            for item in parse_items(html_text):
                if item["itemID"] not in seen:
                    seen.add(item["itemID"])
                    all_items.append(item)

            print(f"    {len(all_items)} items so far")

        browser.close()

    if len(all_items) != total_items:
        print(
            f"  WARNING: expected {total_items} items but scraped {len(all_items)}"
        )

    return all_items


def build_wishlist_xml(items: list[dict], qty: int, max_price: float) -> str:
    lines = ["<INVENTORY>"]
    for item in items:
        lines.append("<ITEM>")
        lines.append("<ITEMTYPE>M</ITEMTYPE>")
        lines.append(f"<ITEMID>{html.escape(item['itemID'])}</ITEMID>")
        lines.append(f"<MINQTY>{qty}</MINQTY>")
        lines.append(f"<MAXPRICE>{max_price:.2f}</MAXPRICE>")
        lines.append("</ITEM>")
    lines.append("</INVENTORY>")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cat_string", help="BrickLink category ID, e.g. 768 for Super Heroes")
    parser.add_argument("--json-out", default=None, help="Path to save scraped item list as JSON")
    parser.add_argument("--xml-out", default=None, help="Path to save Wanted List XML")
    parser.add_argument("--qty", type=int, default=DEFAULT_QTY, help=f"MINQTY per item (default {DEFAULT_QTY})")
    parser.add_argument("--max-price", type=float, default=DEFAULT_MAX_PRICE, help=f"MAXPRICE per item (default {DEFAULT_MAX_PRICE:.2f})")
    args = parser.parse_args()

    json_out = Path(args.json_out or f"category_{args.cat_string}_items.json")
    xml_out = Path(args.xml_out or f"category_{args.cat_string}_wishlist.xml")

    print(f"Scraping category {args.cat_string}...")
    items = scrape_category(args.cat_string)
    print(f"\n{len(items)} minifigs found.")

    json_out.write_text(json.dumps(items, indent=2))
    print(f"Saved item list to {json_out}")

    xml = build_wishlist_xml(items, args.qty, args.max_price)
    xml_out.write_text(xml)
    print(f"Saved Wanted List XML to {xml_out}")
    print("\nUpload at: https://www.bricklink.com/v2/wanted/upload.page")


if __name__ == "__main__":
    main()
