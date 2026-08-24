"""Extract normalized machine specs from GovDeals lot titles and spec-sheet PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------- CPU parsing

_CPU_PATTERNS = [
    # Intel Core: i7-8700, i5- 8365U (stray space), i9-13900K
    (re.compile(r"\bi([3579])\s*-\s*(\d{3,5})\s*([a-z]{0,2})\b", re.I),
     lambda m: f"i{m.group(1)}-{m.group(2)}{m.group(3).lower()}"),
    # Xeon: E5-1650, E3-1270 v5
    (re.compile(r"\b(e[35])\s*-\s*(\d{4})\s*(v\d)?\b", re.I),
     lambda m: f"{m.group(1).lower()}-{m.group(2)}{(' ' + m.group(3).lower()) if m.group(3) else ''}"),
    # Xeon W: W-2123, W2223
    (re.compile(r"\bw\s*-?\s*(\d{4})\b", re.I), lambda m: f"w-{m.group(1)}"),
    # AMD Ryzen
    (re.compile(r"\bryzen\s*([3579])\s*(\d{4})([a-z]{0,2})\b", re.I),
     lambda m: f"ryzen{m.group(1)}-{m.group(2)}{m.group(3).lower()}"),
    # Older Core 2 / Pentium / Celeron
    (re.compile(r"\b(core\s*2\s*duo|pentium|celeron|atom)\b", re.I),
     lambda m: m.group(1).lower().replace(" ", "")),
]

# Intel Core generation from the model number
def cpu_generation(cpu: str) -> int | None:
    m = re.match(r"i[3579]-(\d{3,5})", cpu or "")
    if not m:
        return None
    n = m.group(1)
    return int(n[:2]) if len(n) == 5 else int(n[0])


def parse_cpu(text: str) -> str | None:
    """Return a normalized CPU id like 'i7-8700', 'e5-1650 v3', 'w-2123'."""
    if not text:
        return None
    for pat, fmt in _CPU_PATTERNS:
        m = pat.search(text)
        if m:
            return fmt(m)
    return None


# ------------------------------------------------------- form factor / chassis

_FORM = [
    ("aio",       r"\baio\b|all[\s-]*in[\s-]*one"),
    ("micro",     r"\bmicros?\b|\bmff\b|\btiny\b|\busff\b"),
    ("sff",       r"\bsff'?s?\b|small\s*form"),
    ("tower",     r"\btowers?\b|\bmt\b|\bdesktops?\b|\bdt\b"),
    ("laptop",    r"\blaptops?\b|latitude|thinkpad|elitebook|probook|\bnotebooks?\b"),
    ("workstation", r"precision|workstation|\bxeon\b"),
]


def parse_form_factor(text: str) -> str | None:
    t = (text or "").lower()
    for name, pat in _FORM:
        if re.search(pat, t):
            return name
    return None


def parse_ram_gb(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*GB\s*(?:of\s*)?(?:DDR\d\s*)?RAM|\bRAM[:\s]*(\d{1,3})\s*GB", text or "", re.I)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def has_storage(text: str) -> bool | None:
    t = (text or "").upper()
    if re.search(r"NO (HARD DRIVE|HDD|SSD|DRIVE|STORAGE)|NO SSD'?S|WITHOUT (HDD|SSD)", t):
        return False
    if re.search(r"\b\d+\s*(GB|TB)\s*(HDD|SSD|NVME|HARD DRIVE)\b", t):
        return True
    return None


_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

# Ordered most-specific first. Sellers are wildly inconsistent about this.
_COUNT_PATTERNS = [
    # "LOT OF (192) HP PRODESK", "Lot of 48 Dell"
    re.compile(r"\blots?\s+of\s*\(?\s*(\d{1,4})\s*\)?", re.I),
    # "Three (3) Dell OptiPlex", "Two (2) Monitors"
    re.compile(r"\b(?:" + "|".join(_WORD_NUM) + r")\s*\(\s*(\d{1,4})\s*\)", re.I),
    # "(144) HP ProDesk ..." at the start
    re.compile(r"^\s*\(\s*(\d{1,4})\s*\)", re.I),
    # "232x Dell OptiPlex", "130x Dell and Lenovo"
    re.compile(r"\b(\d{1,4})\s*x\s+(?=[A-Za-z])", re.I),
    # auctioneer count notation: "(ct.194)", "(ct 194)"
    re.compile(r"\bct\.?\s*(\d{1,4})\b", re.I),
    # "Qty 40", "Quantity: 40", "40 EA"
    re.compile(r"\bqty\.?[:\s]+(\d{1,4})\b", re.I),
    re.compile(r"\bquantity[:\s]+(\d{1,4})\b", re.I),
    re.compile(r"\b(\d{1,4})\s*ea\b", re.I),
    # "LAPTOPS APPROX 150", "approximately 26"
    re.compile(r"\bapprox(?:imately)?\.?\s*(\d{1,4})\b", re.I),
    # "(26 Items)", "(40 units)", "50 pieces"
    re.compile(r"\(?\s*(\d{1,4})\s*(?:items?|units?|pieces?|pcs?)\b", re.I),
    # a parenthesised count anywhere: "... and fifty (1750) Lenovo 100e".
    # Not "(LOT 1)", "(ID #47379)" or "(26-2144-5)", which are labels.
    re.compile(r"(?<![\w#])\(\s*(\d{1,4})\s*\)\s*(?=[A-Za-z])", re.I),
    # a bare count after a lead-in: "Bulk Auction: 40 Dell Latitude 7320"
    re.compile(r"(?:^|[:\u2013\u2014]\s*|\s-\s)\s*(\d{1,4})\s+"
               r"(?!GB|TB|MB|GHZ|MHZ|IN\b|\")", re.I),
    # leading bare count: "137 Various Brands/Models of Micro Computers"
    re.compile(r"^\s*(\d{1,4})\s+(?!GB|TB|MB|GHZ|MHZ|IN\b|\")", re.I),
]

# Plural nouns that mean "more than one machine" even with no number given.
_PLURAL_HINT = re.compile(
    r"\b(computers|desktops|towers|laptops|workstations|pcs|machines|"
    r"monitors|sff'?s|aio'?s)\b", re.I)


def parse_unit_count(title: str) -> int | None:
    """Number of machines in a lot.

    Handles 'Lot of 48', 'LOT OF (192)', '(144) HP ProDesk', 'Three (3) Dell',
    '137 Various Brands', 'Qty 40'. Returns 1 for an apparent single machine,
    and None when the title is plural but gives no count -- callers should treat
    None as 'unknown count', never as 1.
    """
    t = title or ""
    for pat in _COUNT_PATTERNS:
        m = pat.search(t)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 2000:
                return n
    for w, n in _WORD_NUM.items():
        if re.search(rf"\b{w}\s+(?:assorted\s+|various\s+)?\w*\s*(?:computers|desktops|towers|laptops)\b", t, re.I):
            return n
    if _PLURAL_HINT.search(t):
        return None      # plural, count unknown -- do NOT assume 1
    return 1


# -------------------------------------------------------------- machine record

@dataclass
class Machine:
    """One physical machine (or N identical ones) with known specs."""
    cpu: str | None = None
    generation: int | None = None
    ram_gb: int | None = None
    form_factor: str | None = None
    chassis: str | None = None      # e.g. "9020", "7060"
    has_drive: bool | None = None
    qty: int = 1

    def to_dict(self):
        return asdict(self)


# A chassis is a 4-digit model or an alphanumeric one (XE2, XE3), but only when it
# follows a product line or stands alone -- never when it is part of the CPU token.
_CHASSIS = re.compile(
    r"\b(?:optiplex|precision|latitude|thinkcentre|prodesk|elitedesk|imac)\s+"
    r"(?:t|mt)?(\d{3,4}|xe\d)\b", re.I)
_CHASSIS_BARE = re.compile(r"\b(\d{4}|xe\d)\b", re.I)


def parse_chassis(text: str, cpu: str | None) -> str | None:
    """Model number of the machine, e.g. '9020', '7060', 'XE3'.

    The CPU token is removed first so 'i7-8700' does not read as chassis 8700
    and 'E5-1650' does not read as chassis 1650.
    """
    if not text:
        return None
    t = text
    if cpu:
        # blank out anything that looks like the CPU part number
        t = re.sub(r"\b[a-z]?\d?\s*-?\s*\d{3,5}\s*[a-z]{0,2}\b(?=\s*(@|,|$|\s))", " ", t, flags=re.I)
    m = _CHASSIS.search(text)
    if m:
        return m.group(1).upper()
    m = _CHASSIS_BARE.search(t)
    return m.group(1).upper() if m else None


def machine_from_text(text: str, qty: int = 1) -> Machine:
    cpu = parse_cpu(text)
    return Machine(
        cpu=cpu,
        generation=cpu_generation(cpu) if cpu else None,
        ram_gb=parse_ram_gb(text),
        form_factor=parse_form_factor(text),
        chassis=parse_chassis(text, cpu),
        has_drive=has_storage(text),
        qty=qty,
    )


# ---------------------------------------------------------------- PDF manifest

_ROW = re.compile(
    r"^\s*(?P<cpu>[a-z]?\d?[-\w]*?\d[-\w]*)\s*@\s*(?P<ghz>[\d.]+)\s*GHZ\s*,"
    r"(?P<mid>.*?):\s*(?P<qty>\d+)\s*$",
    re.I,
)
_CHASSIS_HDR = re.compile(r"^([A-Z0-9][A-Z0-9 /'\-]{1,30})'?S?:?\s*$")


def parse_manifest_pdf(path: str) -> list[Machine]:
    """Parse a seller spec-sheet PDF into Machine rows.

    Handles the UI Surplus format:
        9020 TOWERS:
        I7-4790 @ 3.60 GHZ, NO HARD DRIVE, 8 GB RAM: 4
    """
    import pypdf

    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)
    out: list[Machine] = []
    chassis, form = None, None
    for raw in text.splitlines():
        line = raw.strip().replace("’", "'")
        if not line:
            continue
        m = _ROW.match(line)
        if not m:
            if line.endswith(":") or _CHASSIS_HDR.match(line):
                hdr = line.rstrip(":").strip()
                # ignore the document title line ("48 DELL OPTIPLEX COMPUTER SPECS")
                if re.search(r"\bspecs?\b", hdr, re.I):
                    form = parse_form_factor(hdr)
                    continue
                cm = re.search(r"\b(\d{4}|xe\d)\b", hdr, re.I)
                chassis = cm.group(1).upper() if cm else chassis
                form = parse_form_factor(hdr) or form
            continue
        cpu = parse_cpu(m.group("cpu")) or m.group("cpu").lower()
        mid = m.group("mid")
        ram = re.search(r"(\d{1,3})\s*GB", mid, re.I)
        out.append(Machine(
            cpu=cpu,
            generation=cpu_generation(cpu),
            ram_gb=int(ram.group(1)) if ram else None,
            form_factor=form,
            chassis=chassis,
            has_drive=has_storage(mid),
            qty=int(m.group("qty")),
        ))
    return out
