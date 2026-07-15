#!/usr/bin/env python3
"""
BrickLink Order Summary

Scans your BrickLink "Orders Placed" list (orderPlaced.asp) for orders
placed on a given date, opens each matching order's detail page, and
reports the number of minifigs and total amount paid.

Usage:
  python order_summary.py                    # today's orders
  python order_summary.py --date "Jul 3, 2026"
"""

import re
import time
import argparse
import datetime
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "session.json"
DELAY = 1.0  # seconds between page loads — be polite

CAD_PER_USD = 1.42  # fixed rate: 1 USD = 1.42 CAD


def to_usd(currency: str, amount: float) -> float | None:
    if currency == "US":
        return amount
    if currency == "CA":
        return amount / CAD_PER_USD
    return None

LAUNCH_ARGS = ["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0"


def new_browser(p):
    browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
    context = browser.new_context(storage_state=str(SESSION_FILE), user_agent=USER_AGENT)
    page = context.new_page()
    return browser, context, page


def load_page(page, url: str) -> str:
    """Navigate to url, waiting out the AWS WAF JS challenge if it appears."""
    page.goto(url, wait_until="load", timeout=30000)
    content = page.content()
    if "challenge-container" in content:
        time.sleep(6)
        page.wait_for_load_state("networkidle", timeout=20000)
        content = page.content()
    return content


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


# ── Order list parsing ────────────────────────────────────────────────────────

ORDER_LIST_TOTAL_RE = re.compile(
    r"Total\s*<b>(\d+)</b>\s*Orders Placed\.\s*Page\s*<b>\d+</b>\s*of\s*<b>(\d+)</b>"
)
ORDER_ID_RE = re.compile(r'<a href="orderDetail\.asp\?ID=(\d+)">\1</a>')
ORDER_DATE_RE = re.compile(r'<td nowrap="">([A-Za-z]{3} \d{1,2}, \d{4})</td>')
ORDER_STATUS_RE = re.compile(r'<b><font color="[0-9A-Fa-f]+">([^<]+)</font></b>')
ORDER_ROW_WINDOW = 2000


def parse_order_totals(html_text: str) -> tuple[int, int]:
    m = ORDER_LIST_TOTAL_RE.search(html_text)
    if not m:
        return (0, 1)
    return (int(m.group(1)), int(m.group(2)))


def parse_order_rows(html_text: str) -> list[dict]:
    rows = []
    for m in ORDER_ID_RE.finditer(html_text):
        chunk = html_text[m.start(): m.start() + ORDER_ROW_WINDOW]
        date_m = ORDER_DATE_RE.search(chunk)
        status_m = ORDER_STATUS_RE.search(chunk)
        rows.append({
            "orderID": m.group(1),
            "date": date_m.group(1) if date_m else None,
            "status": status_m.group(1).strip() if status_m else None,
        })
    return rows


def parse_bricklink_date(date_str: str) -> datetime.date:
    return datetime.datetime.strptime(date_str, "%b %d, %Y").date()


# ── Order detail parsing ──────────────────────────────────────────────────────

ITEM_ROW_RE = re.compile(
    r'catalogitem\.page\?M=([^"]+)".*?'
    r'<td align="RIGHT">&nbsp;</td>'
    r'<td align="RIGHT" class="_bltRightAlign">(\d+)</td>'
    r'<td align="RIGHT" class="_bltRightAlign"><span class="currSign">[A-Z]{2}&nbsp;\$</span>[\d,]+\.\d+</td>'
    r'<td align="RIGHT" class="_bltRightAlign"><span class="currSign">[A-Z]{2}&nbsp;\$</span>([\d,]+\.\d+)</td>',
    re.S,
)
SERIES_RE = re.compile(r"^[A-Za-z]+")


def item_series(item_id: str) -> str:
    m = SERIES_RE.match(item_id)
    return m.group(0) if m else item_id
PAY_GRAND_TOTAL_RE = re.compile(
    r'Pay&nbsp;Grand&nbsp;Total:</td>\s*<td[^>]*><b>([A-Z]{2})&nbsp;\$([\d,]+\.\d+)</b></td>'
)
GRAND_TOTAL_RE = re.compile(
    r'Grand&nbsp;Total:</td>\s*<td[^>]*>(?:<b>)?([A-Z]{2})&nbsp;\$([\d,]+\.\d+)(?:</b>)?</td>'
)
SELLER_SECTION_RE = re.compile(r"Seller Information</b>(.*)", re.S)
STORE_NAME_RE = re.compile(r'Store Name:</td><td[^>]*><b>([^<]+)</b>')
USERNAME_RE = re.compile(r'Username:</td><td[^>]*><b>([^<]+)</b>')


def parse_order_detail(html_text: str) -> dict:
    items = [
        {
            "item_id": item_id,
            "series": item_series(item_id),
            "qty": int(qty),
            "ext_price": float(ext_price.replace(",", "")),
        }
        for item_id, qty, ext_price in ITEM_ROW_RE.findall(html_text)
    ]
    figs = sum(i["qty"] for i in items)

    pay_m = PAY_GRAND_TOTAL_RE.search(html_text)
    if pay_m:
        currency, amount = pay_m.group(1), pay_m.group(2)
    else:
        gt_m = GRAND_TOTAL_RE.search(html_text)
        currency, amount = (gt_m.group(1), gt_m.group(2)) if gt_m else (None, None)

    seller_section_m = SELLER_SECTION_RE.search(html_text)
    seller_section = seller_section_m.group(1) if seller_section_m else ""
    store_m = STORE_NAME_RE.search(seller_section)
    user_m = USERNAME_RE.search(seller_section)
    seller = store_m.group(1) if store_m else (user_m.group(1) if user_m else None)

    return {
        "figs": figs,
        "currency": currency,
        "amount_paid": float(amount.replace(",", "")) if amount else None,
        "seller": seller,
        "items": items,
    }


# ── Main flow ─────────────────────────────────────────────────────────────────

def find_orders_for_date(p, browser, context, page, target_date: datetime.date) -> list[dict]:
    """Walk order list pages (newest-first) collecting orders matching target_date."""
    matches: list[dict] = []

    first_url = "https://www.bricklink.com/orderPlaced.asp?pg=1"
    print("  Fetching order list page 1...")
    browser, context, page, html_text = load_page_with_retry(p, browser, context, page, first_url)
    total_orders, total_pages = parse_order_totals(html_text)
    print(f"  {total_orders} orders on file across {total_pages} page(s)")

    for pg in range(1, total_pages + 1):
        if pg > 1:
            url = f"https://www.bricklink.com/orderPlaced.asp?pg={pg}"
            print(f"  Fetching order list page {pg}...")
            browser, context, page, html_text = load_page_with_retry(p, browser, context, page, url)
            time.sleep(DELAY)

        stop = False
        for row in parse_order_rows(html_text):
            row_date = parse_bricklink_date(row["date"]) if row["date"] else None
            if row_date == target_date:
                matches.append(row)
            elif row_date and row_date < target_date:
                stop = True
        if stop:
            break

    return browser, context, page, matches


def summarize(target_date: datetime.date):
    with sync_playwright() as p:
        browser, context, page = new_browser(p)

        browser, context, page, matches = find_orders_for_date(p, browser, context, page, target_date)

        cancelled = [row for row in matches if row["status"] and "cancel" in row["status"].lower()]
        matches = [row for row in matches if row not in cancelled]
        if cancelled:
            print(f"\nExcluding {len(cancelled)} cancelled order(s): "
                  f"{', '.join('#' + c['orderID'] for c in cancelled)}")

        print(f"\n{len(matches)} order(s) found for {target_date.strftime('%b %d, %Y')}\n")

        results = []
        for row in matches:
            order_id = row["orderID"]
            url = f"https://www.bricklink.com/orderDetail.asp?ID={order_id}"
            print(f"  Fetching order {order_id}...")
            browser, context, page, html_text = load_page_with_retry(p, browser, context, page, url)
            time.sleep(DELAY)
            detail = parse_order_detail(html_text)
            results.append({"orderID": order_id, **detail})

        browser.close()

    total_figs = sum(r["figs"] for r in results)
    by_currency: dict[str, float] = defaultdict(float)
    for r in results:
        if r["currency"] and r["amount_paid"] is not None:
            by_currency[r["currency"]] += r["amount_paid"]

    # Weighted allocation: each item's share of the order's item subtotal
    # (by extended price) is applied to that order's amount_paid, so tax/
    # shipping/currency-conversion get distributed proportionally too.
    series_figs: dict[str, int] = defaultdict(int)
    series_paid: dict[tuple[str, str], float] = defaultdict(float)
    for r in results:
        items = r["items"]
        subtotal = sum(i["ext_price"] for i in items)
        for i in items:
            series_figs[i["series"]] += i["qty"]
            if subtotal > 0 and r["amount_paid"] is not None and r["currency"]:
                weight = i["ext_price"] / subtotal
                series_paid[(i["series"], r["currency"])] += weight * r["amount_paid"]

    print(f"\n{'='*60}")
    print(f"  Orders on {target_date.strftime('%b %d, %Y')}")
    print(f"{'='*60}")
    for r in results:
        amt = f"{r['currency']} ${r['amount_paid']:.2f}" if r["amount_paid"] is not None else "?"
        print(f"  #{r['orderID']:<10} {r['seller'] or '?':<25} {r['figs']:>3} figs   {amt}")
    print(f"{'-'*60}")
    print(f"  Total orders : {len(results)}")
    print(f"  Total figs   : {total_figs}")
    for currency, amount in sorted(by_currency.items()):
        print(f"  Total paid   : {currency} ${amount:.2f}")
    total_usd_equiv = sum(
        usd for cur, amt in by_currency.items() if (usd := to_usd(cur, amt)) is not None
    )
    print(f"  Total paid   : US ${total_usd_equiv:.2f} equiv (CAD @ {CAD_PER_USD}/USD)")
    if total_figs > 0:
        print(f"  Per fig      : US ${total_usd_equiv / total_figs:.2f}")
    print(f"{'='*60}")

    print(f"\n{'='*60}")
    print(f"  By Series (weighted by item price share of each order)")
    print(f"{'='*60}")
    paid_by_series: dict[str, dict[str, float]] = defaultdict(dict)
    for (series, currency), amount in series_paid.items():
        paid_by_series[series][currency] = amount
    for series in sorted(series_figs, key=lambda s: -series_figs[s]):
        paid_str = ", ".join(
            f"{cur} ${amt:.2f}" for cur, amt in sorted(paid_by_series[series].items())
        ) or "?"
        usd_equiv = sum(
            usd for cur, amt in paid_by_series[series].items() if (usd := to_usd(cur, amt)) is not None
        )
        per_fig = usd_equiv / series_figs[series] if series_figs[series] else 0.0
        print(
            f"  {series:<8} {series_figs[series]:>4} figs   {paid_str:<28} "
            f"(US ${usd_equiv:.2f} equiv, US ${per_fig:.2f}/fig)"
        )
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", default=None,
        help='Date to summarize, e.g. "Jul 4, 2026" (default: today)'
    )
    args = parser.parse_args()

    target_date = parse_bricklink_date(args.date) if args.date else datetime.date.today()

    print(f"Summarizing orders for {target_date.strftime('%b %d, %Y')}...")
    summarize(target_date)


if __name__ == "__main__":
    main()
