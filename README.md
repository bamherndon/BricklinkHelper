# BricklinkHelper

Bulk-orders minifigs from any Bricklink store based on price thresholds, grouped by theme.

---

> [!WARNING]
> **Bricklink API Rate Limit: 5,000 calls/day**
>
> This script makes multiple API calls per run — one call to resolve the store ID, then one call per page of inventory (200 items/page). A store with 1,000 minifigs = ~5 calls per dry run. **Running `--buy` doubles the call count** (inventory fetch + one cart-add call per item added).
>
> **Tips to stay under the limit:**
> - Don't run the script repeatedly back-to-back on large stores.
> - Avoid scripting or looping automated runs.
> - If you hit the limit, all API calls will fail until midnight UTC resets your quota.

---

## How It Works

Calls the Bricklink store's internal JSON API directly using a saved browser session — no DOM scraping. Scans a store's entire minifig inventory, filters by price rules, and prints a breakdown by theme. In `--buy` mode it prompts you theme-by-theme (y/N) before adding anything to cart.

**Pricing rules:**
- Town minifigs — $3.00 or less
- All other minifigs — $5.00 or less

## Setup

**1. Install dependencies**
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
```

**2. Log in and save your session**
```bash
venv/bin/python bulk_order.py --save-session
```
A browser window will open. Log in to Bricklink — the script detects when you're done and saves your session automatically.

If the automated browser can't run reliably in your environment (e.g. a flaky display/compositor), see [Importing a Session from Your Regular Browser](#importing-a-session-from-your-regular-browser) for an alternative that doesn't need a browser window at all.

## Usage

```bash
# Dry run — shows per-theme item list and summary (no cart changes)
venv/bin/python bulk_order.py <store_name>

# Interactive buy — reviews each theme and prompts y/N before adding to cart
venv/bin/python bulk_order.py <store_name> --buy
```

`<store_name>` is the store's username as it appears in the URL:
`https://store.bricklink.com/PremiumBrick` → store name is `PremiumBrick`

## Example Output

```
Resolving store ID for 'PremiumBrick'...
  sid = 848359

Fetching minifig inventory...
  Page 1: 200 items  (200/986 total)
  ...
  986 minifig lots found

Qualifying items : 637
Skipped (price)  : 349

════════════════════════════════════════════════════════════
  Dry Run — Would Order Summary
════════════════════════════════════════════════════════════
  THEME                      FIGS     TOTAL
  ────────────────────────  ─────  ────────
  Collectible Minifigures     100  $ 385.24
  Star Wars                    83  $ 306.86
  DUPLO                        53  $  99.92
  Harry Potter                 47  $ 165.27
  Town                         46  $  87.98
  ...
  ────────────────────────  ─────  ────────
  TOTAL                       637  $1870.50
════════════════════════════════════════════════════════════
```

## Adjusting Prices

Edit the constants at the top of `bulk_order.py`:

```python
TOWN_CAT_ID       = 67    # Bricklink category ID for Town minifigs
TOWN_MAX_PRICE    = 3.00
DEFAULT_MAX_PRICE = 5.00
```

## Using with Claude Code

You can ask Claude Code to run the script for you with natural language:

- *"Dry run on store PremiumBrick"* → runs `venv/bin/python bulk_order.py PremiumBrick`
- *"Buy minifigs from PremiumBrick"* → runs with `--buy` and handles the interactive prompts
- *"Save my Bricklink session"* → runs `--save-session`

Claude will read the output and summarize results. For `--buy` mode, tell Claude which themes to accept or skip (e.g. *"skip DUPLO and Duplo, buy everything else"*).

## Session Expiry

Sessions expire periodically. If you start seeing API errors or empty results, re-run:
```bash
venv/bin/python bulk_order.py --save-session
```

## Category Wishlist Builder

A second, separate tool — `category_wishlist.py` — takes a different approach: instead of
ordering from one store, it scrapes BrickLink's public catalog for an entire minifig
category and builds a Wanted List XML file for bulk upload.

**How it works:** renders `catalogList.asp?catType=M&catString=<id>` with Playwright
(needed to get past BrickLink's AWS WAF JS challenge), walks every page, and collects
every item's ID and name. The catalog list page doesn't expose price data, so this tool
captures the whole category rather than filtering by price — every item gets the same
`MINQTY`/`MAXPRICE` in the generated XML. No login/session is required — the catalog is
public.

```bash
venv/bin/python category_wishlist.py <catString> [--qty N] [--max-price PRICE]

# Example: Super Heroes, default qty=2, max price=$5.00
venv/bin/python category_wishlist.py 768

# Example: want 3 of each, up to $7.50
venv/bin/python category_wishlist.py 768 --qty 3 --max-price 7.50
```

`<catString>` is the category ID from a `catalogList.asp` URL, e.g.
`https://www.bricklink.com/catalogList.asp?catType=M&catString=768` → `768`.

`--qty` sets `MINQTY` per item (default `2`). `--max-price` sets `MAXPRICE` per item
(default `5.00`).

**Output:**
- `category_<id>_items.json` — raw scraped item list (item ID + name)
- `category_<id>_wishlist.xml` — Wanted List XML, ready to paste in at
  https://www.bricklink.com/v2/wanted/upload.page

## Importing a Session from Your Regular Browser

If `--save-session`'s automated browser window can't log in reliably (crashes, flaky
display, etc.), you can import a session from your everyday browser instead:

1. Log into https://www.bricklink.com in your regular browser.
2. Install a cookie-export extension (e.g. "Cookie-Editor" for Chrome/Firefox).
3. On a bricklink.com page, open the extension and **Export → Export as JSON**, saving
   the result to a file.
4. Run:
   ```bash
   venv/bin/python import_session.py <exported_cookies.json>
   ```
   This converts the export into `session.json` in the format all the other scripts
   expect — no automated browser login needed.

## Order Summary

`order_summary.py` scans your BrickLink **Orders Placed** list (`orderPlaced.asp`) for
orders placed on a given date, opens each matching order's detail page, and reports the
number of minifigs and total amount paid — both overall and broken down by minifig
series (the letter prefix of the item ID, e.g. `sh` = Super Heroes, `cty` = City).

```bash
venv/bin/python order_summary.py                     # today's orders
venv/bin/python order_summary.py --date "Jul 3, 2026" # a specific date
```

**How amounts are calculated:**
- Each order's "amount paid" prefers the buyer-currency **Pay Grand Total** (the actual
  charged amount after currency conversion); it falls back to the plain **Grand Total**
  when no conversion applies (same currency, or the order is still Pending and BrickLink
  hasn't computed a conversion yet). Amounts in different currencies are kept separate,
  not converted or summed together.
- The per-series breakdown uses **weighted allocation**: each item's share of its
  order's item subtotal (by extended price) is applied to that order's total amount
  paid, so tax/shipping/conversion gets distributed proportionally across items rather
  than only summing list prices.

Requires `session.json` (see Setup or [Importing a Session from Your Regular
Browser](#importing-a-session-from-your-regular-browser)).
