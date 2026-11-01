"""World Bank Commodity Price Data ("Pink Sheet") — monthly gold price since 1960.

Official, free, CC BY 4.0, no key. The file name stays the same but its
address changes with every monthly update, so the current link is read from
the World Bank commodity-markets page (robots.txt allows it). Checked live
2026-10-06: file "Updated on October 02, 2026", sheet "Monthly Prices",
gold column headed "Gold", rows "YYYYMmm" from 1960M01 to the last full month.

Values are MONTHLY AVERAGES of daily London prices — good for seasonality
(5/10/15-year averages), not for trading levels.
Fetched at most once a day.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import threading
import xml.etree.ElementTree as ET
import zipfile

import httpx

PAGE_URL = "https://www.worldbank.org/en/research/commodity-markets"
LINK_RE = re.compile(r"https://thedocs\.worldbank\.org/[^\"'<>\s]*CMO-Historical-Data-Monthly\.xlsx")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
CACHE_HOURS = 24

_cache: dict[str, object] = {"at": None, "data": None}
_lock = threading.Lock()


class WorldBankUnavailableError(RuntimeError):
    pass


def _col(ref: str) -> str:
    m = re.match(r"[A-Z]+", ref)
    return m.group(0) if m else ""


def parse_gold(xlsx: bytes) -> dict:
    """{"updated": "October 02, 2026", "prices": {"2026-09": 4123.4, ...}} from the Pink Sheet workbook."""
    try:
        z = zipfile.ZipFile(io.BytesIO(xlsx))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        sheet_rid = next(s.attrib[REL_ID] for s in wb.find("m:sheets", NS) if s.attrib.get("name") == "Monthly Prices")
        target = rels[sheet_rid].lstrip("/")
        target = target if target.startswith("xl/") else f"xl/{target}"
        strings: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in ss]
        rows = ET.fromstring(z.read(target)).find("m:sheetData", NS)
    except (KeyError, StopIteration, zipfile.BadZipFile, ET.ParseError) as exc:
        raise WorldBankUnavailableError(f"soubor Světové banky má nečekaný formát: {exc}") from exc

    def val(c):
        v = c.find("m:v", NS)
        if v is None:
            return None
        return strings[int(v.text)] if c.attrib.get("t") == "s" else v.text

    gold_col, updated, prices = None, None, {}
    for row in rows:
        cells = {_col(c.attrib.get("r", "")): val(c) for c in row}
        first = cells.get("A") or ""
        if isinstance(first, str) and first.startswith("Updated on"):
            updated = first.replace("Updated on", "").strip()
            try:
                updated = dt.datetime.strptime(updated, "%B %d, %Y").date().isoformat()
            except ValueError:
                pass  # keep the text as published
        if gold_col is None:
            gold_col = next((k for k, v in cells.items() if isinstance(v, str) and v.strip() == "Gold"), None)
            continue
        m = re.fullmatch(r"(\d{4})M(\d{2})", str(first))
        if m and cells.get(gold_col) is not None:
            try:
                prices[f"{m.group(1)}-{m.group(2)}"] = float(cells[gold_col])
            except (TypeError, ValueError):
                continue  # "…" marks a missing month
    if gold_col is None or len(prices) < 120:
        raise WorldBankUnavailableError("ve Pink Sheetu chybí sloupec Gold nebo historie")
    return {"updated": updated, "prices": prices}


def fetch_gold_monthly(now: dt.datetime, client: httpx.Client | None = None) -> dict:
    with _lock:
        at, data = _cache["at"], _cache["data"]
        if isinstance(at, dt.datetime) and data and now - at < dt.timedelta(hours=CACHE_HOURS):
            return data  # type: ignore[return-value]
    owns = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True,
                                    headers={"User-Agent": "Mozilla/5.0 (compatible; fundamental-trading-intelligence/0.6)"})
    try:
        page = client.get(PAGE_URL)
        page.raise_for_status()
        m = LINK_RE.search(page.text)
        if not m:
            raise WorldBankUnavailableError("na stránce Světové banky chybí odkaz na měsíční ceny")
        resp = client.get(m.group(0))
        resp.raise_for_status()
        data = parse_gold(resp.content)
        data["url"] = m.group(0)
    except httpx.HTTPError as exc:
        raise WorldBankUnavailableError(str(exc)) from exc
    finally:
        if owns:
            client.close()
    with _lock:
        _cache["at"], _cache["data"] = now, data
    return data
