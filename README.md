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
