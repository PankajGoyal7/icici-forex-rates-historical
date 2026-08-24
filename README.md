# icici-forex-rates-historical

Historical ICICI Bank **Forex Card Rates**, captured daily via GitHub
Actions from:

https://www.icici.bank.in/corporate/global-markets/forex/forex-card-rate

Inspired by [`skbly7/sbi-tt-rates-historical`](https://github.com/skbly7/sbi-tt-rates-historical)
and [`sahilgupta/sbi-fx-ratekeeper`](https://github.com/sahilgupta/sbi-fx-ratekeeper),
but stores clean CSV instead of PDFs, since ICICI's page is already a
structured HTML table (no PDF parsing needed).

## Why

ICICI (like SBI) only shows *today's* card rate on their site and doesn't
publish history. This repo runs a scraper on a schedule so you build up a
historical record over time — useful for ITR/tax filing, expense
reconciliation, or just tracking rate movement.

**Card rates are not the same as RBI reference rates or interbank rates.**
They include the bank's markup on cash/prepaid-card conversion. Use
accordingly.

## Data layout

```
data/
├── historical.csv           # every row ever captured, all currencies, appended daily
├── by_currency/
│   ├── USD.csv               # just USD rows, across all dates
│   ├── EUR.csv
│   └── ...
└── snapshots/
    └── 2026/
        └── 08/
            └── 2026-08-24-1000.csv   # raw snapshot for that run
```

Each row has:

| column | meaning |
|---|---|
| `fetch_date` / `fetch_time` | when the Action ran (IST) |
| `page_date` / `page_time` | the "Date:"/"Time:" ICICI printed on the page itself |
| `currency_name` / `currency_code` | e.g. `United States Dollar` / `USD` |
| `tt_buying`, `bills_buying`, `currency_notes_buying`, `forex_card_buying`, `demand_draft_buying` | Bank Buying Rate columns |
| `tt_selling`, `bills_selling`, `currency_notes_selling`, `forex_card_selling`, `demand_draft_selling` | Bank Selling Rate columns |

Blank cells mean ICICI didn't publish a rate for that combination that day
(this is normal — not every currency has every rate type).

## Running it yourself

```bash
pip install -r requirements.txt
python scripts/fetch_icici_rates.py          # skips if today's already captured
python scripts/fetch_icici_rates.py --force  # re-fetch anyway
```

## Automation

`.github/workflows/daily.yml` runs the scraper Mon–Sat at 10:00 IST
(04:30 UTC) — after ICICI's ~09:15 IST publish time — and commits any new
rows straight to `main`. Trigger it manually from the Actions tab
(`workflow_dispatch`) any time, including with `force: true` to re-fetch a
day that was already captured.

No secrets are required beyond the default `GITHUB_TOKEN` (already scoped
with `contents: write` in the workflow).

## Caveats

- ICICI can change their page markup at any time; the parser looks for a
  `<table>` containing "TT Buying" text and rows shaped like
  `"Currency Name (CODE)"`, rather than hardcoding table position, but a
  bigger redesign will still break it — check the Action logs / open an
  issue if a run fails.
- Rates shown apply to transactions up to USD 25,000 equivalent per
  ICICI's own notes on the page; larger amounts are slab-based.
- This is unofficial and not affiliated with ICICI Bank. Rates are
  captured as published and may differ from the rate actually applied to
  any given transaction (which is the rate prevailing at time of
  debit/credit).
