"""
Minimal client for the GovDeals / AllSurplus "maestro" JSON API.

Discovered by instrumenting the Angular bundle at www.govdeals.com:
  maestroUrl     = https://maestro.lqdt1.com
  maestroApiKey  = af93060f-337e-428c-87b8-c74b5837d6cd   (public client key, baked into main.js)
  fileServerUrl  = https://files.lqdt1.com

The API host is NOT behind the Akamai bot manager that guards www.govdeals.com,
so plain HTTP works — no browser, no JS rendering.

Required headers on every call:
  x-api-key             the public client key above
  x-user-id             "-1" for anonymous (0 is rejected)
  x-api-correlation-id  any UUID
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import uuid
import gzip
from dataclasses import dataclass, field

MAESTRO = "https://maestro.lqdt1.com"
FILES = "https://files.lqdt1.com"
API_KEY = "af93060f-337e-428c-87b8-c74b5837d6cd"

# The default urllib User-Agent gets a 403 — any normal browser UA passes.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# GovDeals seller account IDs (the first half of a LOT#, e.g. 7484-44150)
UI_SURPLUS = 7484

FULL_FACETS = [
    "categoryName", "auctionTypeID", "condition", "saleEventName",
    "sellerDisplayName", "product_pricecents", "isReserveMet",
    "hasBuyNowPrice", "isReserveNotMet", "sellerType", "warehouseId",
    "region", "currencyTypeCode", "tierId",
]


def _post(path: str, body: dict) -> tuple[dict, dict]:
    """POST JSON to maestro, return (parsed_body, response_headers)."""
    req = urllib.request.Request(
        f"{MAESTRO}{path}",
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": API_KEY,
            "x-user-id": "-1",
            "x-api-correlation-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": USER_AGENT,
            "Origin": "https://www.govdeals.com",
            "Referer": "https://www.govdeals.com/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return (json.loads(raw) if raw else {}), dict(r.headers)


def search(
    *,
    account_ids: list[int] | None = None,
    text: str = "*",
    sold: bool = False,
    page: int = 1,
    rows: int = 24,
    sort_field: str = "bestfit",
    sort_order: str = "desc",
    category_ids: str = "",
) -> tuple[list[dict], int]:
    """POST /search/list — returns (results, total_count).

    sold=True flips the query to the seller's completed auctions from the last
    ~12 months, via timeType="MicrositeSoldAssets". Those records carry
    isSoldAuction=True and currentBid = the realized hammer price.
    """
    body = {
        "categoryIds": category_ids,
        "businessId": "GD",
        "searchText": text,
        "isQAL": False,
        "locationId": None,
        "model": "",
        "makebrand": "",
        "auctionTypeId": None,
        "page": page,
        "displayRows": rows,
        "sortField": sort_field,
        "sortOrder": sort_order,
        "requestType": "search",
        "responseStyle": "fullResponse",
        "facets": FULL_FACETS,
        "facetsFilter": [],
        "timeType": "MicrositeSoldAssets" if sold else "",
        "sellerTypeId": None,
        "accountIds": account_ids or [],
    }
    data, headers = _post("/search/list", body)
    total = int(headers.get("x-total-count", 0))
    return data.get("assetSearchResults") or [], total


def search_all(*, max_rows: int = 5000, rows: int = 100, **kw) -> list[dict]:
    """Page through search() until exhausted."""
    out, page = [], 1
    while len(out) < max_rows:
        batch, total = search(page=page, rows=rows, **kw)
        if not batch:
            break
        out.extend(batch)
        if len(out) >= total:
            break
        page += 1
    return out[:max_rows]


def asset(asset_id: int, account_id: int) -> dict:
    """POST /assets/{assetId}/{accountId}/false — full lot detail.

    Note the param order: assetId FIRST. The reverse order returns HTTP 204.
    Includes assetLongDesc, assetAttachments, assetPhotos, and location.
    """
    data, _ = _post(
        f"/assets/{asset_id}/{account_id}/false",
        {"businessId": "GD", "siteId": 0},
    )
    return data


def attachment_url(account_id: int, file_name: str) -> str:
    """Public URL for a lot attachment (spec sheets, manifests)."""
    return f"{FILES}/photos/{account_id}/Attachments/{urllib.parse.quote(file_name)}"


def photo_url(path: str) -> str:
    """assetPhotos entries are paths like /photos/7484/7484_44150_<uuid>.jpg"""
    return FILES + path if path.startswith("/") else f"{FILES}/{path}"


def download(url: str, dest: str) -> int:
    req = urllib.request.Request(
        url, headers={"Accept": "*/*", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        n = f.write(r.read())
    return n


# --------------------------------------------------------------------------
# Spec-sheet parsing
# --------------------------------------------------------------------------

@dataclass
class SpecLine:
    """One 'I7-4790 @ 3.60 GHZ, NO HARD DRIVE, 8 GB RAM: 4' row."""
    chassis: str          # e.g. "9020 TOWERS"
    cpu: str              # e.g. "i7-4790"
    ghz: float | None
    ram_gb: int | None
    has_drive: bool
    qty: int
    raw: str = ""


_HDR = re.compile(r"^([A-Z0-9][A-Z0-9 /'’\-]*?[:S]?)\s*:?\s*$")
_ROW = re.compile(
    r"^\s*(?P<cpu>[IiMm]?\d?[-\w]*?\d[-\w]*)\s*@\s*(?P<ghz>[\d.]+)\s*GHZ\s*,"
    r"(?P<mid>.*?):\s*(?P<qty>\d+)\s*$",
    re.I,
)


def parse_spec_pdf(path: str) -> list[SpecLine]:
    """Parse a UI-Surplus-style 'COMPUTER SPECS.pdf' into structured rows.

    Requires pypdf (pip install pypdf).
    """
    import pypdf

    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)
    lines: list[SpecLine] = []
    chassis = ""
    for raw in text.splitlines():
        line = raw.strip().replace("’", "'")
        if not line:
            continue
        m = _ROW.match(line)
        if not m:
            # section header, e.g. "9020 SFF'S:" or "XE2 TOWERS:"
            if line.endswith(":") and not re.search(r"\d\s*$", line):
                chassis = line.rstrip(":").strip()
            continue
        mid = m.group("mid")
        ram = re.search(r"(\d+)\s*GB\s*RAM", mid, re.I)
        lines.append(
            SpecLine(
                chassis=chassis,
                cpu=m.group("cpu").lower(),
                ghz=float(m.group("ghz")),
                ram_gb=int(ram.group(1)) if ram else None,
                has_drive="NO HARD DRIVE" not in mid.upper(),
                qty=int(m.group("qty")),
                raw=line,
            )
        )
    return lines
