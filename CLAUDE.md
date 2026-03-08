# BricklinkHelper — Claude Instructions

## Project Overview
Python tool that bulk-orders minifigs from a Bricklink store using the store's internal AJAX API.
No DOM scraping — all data is fetched via JSON endpoints discovered by network sniffing.

## Running the Script
Always use the project virtualenv:
```bash
venv/bin/python bulk_order.py <store_name>          # dry run — shows per-theme breakdown and summary
venv/bin/python bulk_order.py <store_name> --buy    # interactive per-theme buy (y/N prompt each theme)
venv/bin/python bulk_order.py --save-session        # re-authenticate
```

## Key Files
- `bulk_order.py` — main script (only file that matters for end users)
- `session.json` — saved Playwright browser session (cookies); regenerate with `--save-session`
- `requirements.txt` — `playwright` and `requests`
- `sniff_api.py`, `sniff_cart.py`, `sniff_cart2.py` — dev/debug scripts used during API discovery; not needed for normal use

## Pricing Rules
Defined as constants at the top of `bulk_order.py`:
- `TOWN_CAT_ID = 67` — Bricklink category ID for the Town minifig theme
- `TOWN_MAX_PRICE = 3.00` — Town minifigs at $3.00 or less qualify
- `DEFAULT_MAX_PRICE = 5.00` — all other minifigs at $5.00 or less qualify

To change pricing, edit these constants directly.

## API Details
All calls go to `store.bricklink.com`:
- **Inventory**: `GET /ajax/clone/store/searchitems.ajax?sid=SID&itemType=M&pgSize=PAGE_SIZE&pg=N`
  - `PAGE_SIZE = 200` (Bricklink max appears to be ~500)
- **Cart add**: `POST /ajax/clone/cart/add.ajax` with body `itemArray=[{invID,invQty,sellerID,sourceType}]&sid=SID&srcLocation=1100`
- Required header: `X-Requested-With: XMLHttpRequest`
- Store ID (`sid`) is resolved by launching a headless Playwright browser and capturing it from the first API call URL

## Session Management
- Session is saved to `session.json` via Playwright's `context.storage_state()`
- Login is detected automatically by watching for a Sign Out link
- Sessions expire; re-run `--save-session` when API calls start failing

## Category Map
The category ID → name mapping is fetched from the `categories` field in the first inventory API response. Category IDs are stored as a dot-separated string in each item's `categoryString` field (e.g., `"65.635"` = Star Wars > Clone Wars). The script uses only the top-level ID for grouping.
