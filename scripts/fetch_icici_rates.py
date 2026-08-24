#!/usr/bin/env python3
"""
Fetch ICICI Bank's Forex Card Rate table and store it as historical data.

Source page:
  https://www.icici.bank.in/corporate/global-markets/forex/forex-card-rate

Design (mirrors skbly7/sbi-tt-rates-historical + sahilgupta/sbi-fx-ratekeeper):
  1. Save a dated raw snapshot:      data/snapshots/YYYY/MM/YYYY-MM-DD-HHMM.csv
  2. Append to one running file:     data/historical.csv        (all currencies, long format)
  3. Append to per-currency files:   data/by_currency/<CCY>.csv (easy to chart/diff one currency)

The page renders the rate table server-side (no JS execution required), so a
plain requests + BeautifulSoup parse is sufficient. If ICICI changes their
markup this script will raise instead of silently writing garbage - check the
Action logs.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://www.icici.bank.in/corporate/global-markets/forex/forex-card-rate"

# A real browser UA reduces the chance of being served a bot-block page.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

IST = ZoneInfo("Asia/Kolkata")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
BY_CURRENCY_DIR = DATA_DIR / "by_currency"
HISTORICAL_CSV = DATA_DIR / "historical.csv"

# Column order as it appears on the page (Buying block, then Selling block).
RATE_COLUMNS = [
    "tt_buying",
    "bills_buying",
    "currency_notes_buying",
    "forex_card_buying",
    "demand_draft_buying",
    "tt_selling",
    "bills_selling",
    "currency_notes_selling",
    "forex_card_selling",
    "demand_draft_selling",
]

CSV_FIELDS = [
    "fetch_date",  # date we ran the job, IST, YYYY-MM-DD
    "fetch_time",  # time we ran the job, IST, HH:MM:SS
    "page_date",   # "Date:" shown on the ICICI page
    "page_time",   # "Time:" shown on the ICICI page
    "currency_name",
    "currency_code",
    *RATE_COLUMNS,
]


@dataclass
class RateRow:
    fetch_date: str
    fetch_time: str
    page_date: str
    page_time: str
    currency_name: str
    currency_code: str
    tt_buying: str
    bills_buying: str
    currency_notes_buying: str
    forex_card_buying: str
    demand_draft_buying: str
    tt_selling: str
    bills_selling: str
    currency_notes_selling: str
    forex_card_selling: str
    demand_draft_selling: str

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


class ScrapeError(RuntimeError):
    pass


def fetch_html() -> str:
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _clean(text: str | None) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _split_currency(cell_text: str) -> tuple[str, str]:
    """'United States Dollar (USD)' -> ('United States Dollar', 'USD')"""
    m = re.match(r"^(.*)\(([A-Za-z]{2,4})\)\s*$", cell_text.strip())
    if not m:
        return cell_text.strip(), ""
    return m.group(1).strip(), m.group(2).strip().upper()


def parse_page_date_time(soup: BeautifulSoup) -> tuple[str, str]:
    text = soup.get_text("\n")
    date_m = re.search(r"Date:\s*([0-9]{2}-[0-9]{2}-[0-9]{4})", text)
    time_m = re.search(r"Time:\s*([0-9:]{5,8}\s*[APap][Mm])", text)
    page_date = date_m.group(1) if date_m else ""
    page_time = time_m.group(1).strip() if time_m else ""
    return page_date, page_time


def find_rate_table(soup: BeautifulSoup):
    """
    The rate table is the one whose header row mentions 'TT Buying rate'
    (or similar). We search all <table> elements rather than hardcoding
    position, since surrounding markup shifts often on bank sites.
    """
    for table in soup.find_all("table"):
        header_text = _clean(table.get_text(" "))
        if "TT Buying" in header_text or "TT Buying rate".lower() in header_text.lower():
            return table
    return None


def parse_rates(html: str) -> list[RateRow]:
    soup = BeautifulSoup(html, "html.parser")
    page_date, page_time = parse_page_date_time(soup)

    table = find_rate_table(soup)
    if table is None:
        raise ScrapeError(
            "Could not locate the forex rate table on the page. "
            "ICICI may have changed the page layout - inspect the HTML."
        )

    rows = table.find_all("tr")
    data_rows = []
    for tr in rows:
        cells = [ _clean(td.get_text(" ")) for td in tr.find_all(["td", "th"]) ]
        if not cells:
            continue
        first_cell = cells[0]
        # Skip header / blank / note rows. A real currency row starts with
        # a name followed by "(XXX)" and has the full set of numeric columns.
        if not re.search(r"\([A-Za-z]{2,4}\)\s*$", first_cell):
            continue
        data_rows.append(cells)

    if not data_rows:
        raise ScrapeError(
            "Rate table was found but no currency rows were parsed out of it. "
            "ICICI may have changed the row structure - inspect the HTML."
        )

    now_ist = datetime.now(IST)
    parsed: list[RateRow] = []
    for cells in data_rows:
        name, code = _split_currency(cells[0])
        values = cells[1:]
        # Pad/truncate defensively to the expected 10 rate columns.
        values = (values + [""] * len(RATE_COLUMNS))[: len(RATE_COLUMNS)]
        row = RateRow(
            fetch_date=now_ist.strftime("%Y-%m-%d"),
            fetch_time=now_ist.strftime("%H:%M:%S"),
            page_date=page_date,
            page_time=page_time,
            currency_name=name,
            currency_code=code,
            **dict(zip(RATE_COLUMNS, values)),
        )
        parsed.append(row)

    return parsed


def write_snapshot(rows: list[RateRow], now_ist: datetime) -> Path:
    snapshot_path = (
        SNAPSHOT_DIR
        / f"{now_ist:%Y}"
        / f"{now_ist:%m}"
        / f"{now_ist:%Y-%m-%d-%H%M}.csv"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return snapshot_path


def append_historical(rows: list[RateRow]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = HISTORICAL_CSV.exists()
    with HISTORICAL_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())


def append_by_currency(rows: list[RateRow]) -> None:
    BY_CURRENCY_DIR.mkdir(parents=True, exist_ok=True)
    for row in rows:
        code = row.currency_code or "UNKNOWN"
        path = BY_CURRENCY_DIR / f"{code}.csv"
        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row.as_dict())


def already_captured_today(now_ist: datetime) -> bool:
    """Avoid duplicate rows if the job is re-run same day (e.g. manual re-run)."""
    if not HISTORICAL_CSV.exists():
        return False
    target = now_ist.strftime("%Y-%m-%d")
    with HISTORICAL_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("fetch_date") == target:
                return True
    return False


def main() -> int:
    now_ist = datetime.now(IST)

    if already_captured_today(now_ist) and "--force" not in sys.argv:
        print(f"Rates for {now_ist:%Y-%m-%d} already captured. Use --force to re-fetch.")
        return 0

    html = fetch_html()
    rows = parse_rates(html)

    snapshot_path = write_snapshot(rows, now_ist)
    append_historical(rows)
    append_by_currency(rows)

    print(f"Captured {len(rows)} currency rows.")
    print(f"Snapshot: {snapshot_path.relative_to(REPO_ROOT)}")
    print(f"Appended to: {HISTORICAL_CSV.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
