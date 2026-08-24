"""What is actually in a lot.

The valuation models only ever knew how to price a *machine*: a CPU, some
RAM, maybe a drive. Anything without a recognised CPU fell through to a
generic bucket worth $61-88 a unit, so a pallet of 300 laptop power
adapters priced within a few dollars a unit of a pallet of i7 desktops.
Sold comps say adapters clear about $30 a unit and desktops about $45, and
those are different questions entirely.

So before valuing a lot, decide what kind of thing it holds. Two families:

  computer   desktop, laptop, aio, tablet, server -- priced by the CPU
             feature model, which is what it was built for
  part       adapter, dock, monitor, printer, drive, peripheral, network,
             phone -- priced per unit from sold lots of the same kind

Precision beats recall. A lot we decline to classify stays UNRATED, which
is merely unhelpful; a lot we classify wrongly gets a confident price from
the wrong comps, which is how you overpay. Every rule below errs towards
`None`, and the three that do the most work are worth stating plainly:

  * A term can be what the lot IS or a detail about it. "32GB SSD" and
    "with 24-inch monitor" are details. Only subjects count.
  * English puts the head of a compound noun last and the modifier in the
    singular: "laptop AC adapters" sells adapters, "dell laptops monitors
    and towers" sells three things and is not classifiable at all.
  * A title that itemises -- "(57) Docking Stations, (1) HP PC, (9) Dell
    Monitors" -- is a mixed lot whatever its individual terms say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ------------------------------------------------------------------ taxonomy

COMPUTER_CLASSES = ("aio", "tablet", "server", "laptop", "desktop")
PART_CLASSES = ("adapter", "dock", "monitor", "printer", "drive",
                "peripheral", "network", "phone")
ALL_CLASSES = COMPUTER_CLASSES + PART_CLASSES

# Most specific first: an all-in-one is a desktop and a MacBook is a laptop,
# so whichever narrower term matched should be the one reported.
_SPECIFICITY = {c: i for i, c in enumerate(
    ("adapter", "dock", "drive", "peripheral", "network", "phone", "printer",
     "monitor", "aio", "tablet", "server", "laptop", "desktop"))}

_RULES: list[tuple[str, str]] = [
    ("adapter", r"(?:ac|power)\s*adapters?|chargers?|power\s*(?:brick|block|"
                r"supply|supplies)|power\s*cords?|psus?"),
    ("dock", r"docking\s*stations?|docks?|port\s*replicators?"),
    ("monitor", r"monitors?|displays?"),
    ("printer", r"printers?|copiers?|scanners?|plotters?|toners?"),
    ("phone", r"iphones?|cell\s*phones?|smart\s*phones?|ip\s*phones?|"
              r"handsets?"),
    ("tablet", r"tablets?|ipads?|surface\s*(?:pro|go)\b"),
    ("server", r"servers?|power\s*edge|proliant|rack\s*mount"),
    ("network", r"switch(?:es)?|routers?|firewalls?|access\s*points?"),
    ("drive", r"hard\s*drives?|hdds?|ssds?|nvme|hard\s*disks?"),
    ("peripheral", r"keyboards?|mice\b|mouse|webcams?|headsets?|speakers?|"
                   r"cables?"),
    ("aio", r"all[\s-]*in[\s-]*ones?|\baio'?s?\b|i\s*macs?"),
    # Brand lines are spelled both ways in the wild -- "EliteBook" and
    # "Elite Book", "EliteDesk" and "Elite Desk" -- and a missing space cost
    # us 469 lots that named their product perfectly clearly.
    ("laptop", r"laptops?|note\s*books?|mac\s*books?|chrome\s*books?|"
               r"latitudes?|think\s*pads?|elite\s*books?|pro\s*books?|"
               r"ultra\s*books?"),
    ("desktop", r"desktops?|towers?|opti\s*plex|pro\s*desks?|elite\s*desks?|"
                r"think\s*centres?|precisions?|workstations?|\bpcs?\b|"
                r"computers?|\bsff'?s?\b|\bmicros?\b|chrome\s*box(?:es)?|"
                r"mini\s*pcs?|\bcpus?\b"),
]
_PATTERNS = [(name, re.compile(rf"\b(?:{body})\b", re.I))
             for name, body in _RULES]

# A term can appear as what the lot IS or as a detail about it. The marker
# ("32GB", "with", "no") does not always abut the term -- "256GB NVMe SSD",
# "with 24-inch Monitor" -- so allow a short run of filler, but never across
# a comma or semicolon, which would let one "with" disown the whole title.
# Wattage is deliberately NOT a marker here. "32GB SSD" describes a machine
# that contains a drive, but "65W Charger" describes the charger itself --
# treating watts like gigabytes hid every adapter lot behind its own spec.
_ATTRIBUTE_BEFORE = re.compile(
    r"(?:\d+\s*(?:gb|tb|mb|ghz|mhz|\"|-?inch)s?"
    r"|\b(?:no|without|w/?o|missing|lacks?|with|w/|incl(?:udes|uding)?"
    r"|plus|bundled|includes|for|fits|compatible|replacement)\b)"
    r"[^,;|]{0,16}$",
    re.I,
)
_ATTRIBUTE_LOOKBACK = 44

# A term introduced by a coordinator is one entry in a list, not the thing
# the lot is: "a Microsoft Surface Pro 6 and a Samsung Cell Phone".
_LIST_ITEM_BEFORE = re.compile(r"(?:,|&|\+|\band\b)\s*(?:an?|the)?\s*"
                               r"(?:\w+[\s/-]+){0,3}$", re.I)

# Phrases that say the lot is a grab bag, and the itemised form of the same
# thing -- two or more parenthesised counts, each naming a different item.
_GRAB_BAG = re.compile(
    r"\b(?:assorted|misc(?:ellaneous)?|mixed\s+(?:lot|items|electronics|"
    r"equipment|bag)|various\s+(?:items|equipment|electronics)|e-?waste|"
    r"scrap|salvage|surplus\s+items|grab\s*bag)\b", re.I)
_PAREN_COUNT = re.compile(r"\(\s*\d{1,4}\s*\)")

# Things sold FOR computers rather than computers. "TRANSIT CASE for 12
# Notebooks, Laptops" is sixteen empty cases; "Monitor Stand Bases" is
# ninety-six lumps of plastic. Both read as their contents to any rule that
# only looks for product words, and neither is something we have comps for.
_CONTAINER = re.compile(
    r"\b(?:cases?|bags?|sleeves?|covers?|carts?|trolleys?|racks?|trays?|"
    r"brackets?|(?<!rack )mounts?|stands?|bases?|risers?|arms?|"
    r"cabinets?|carrying)\b", re.I)

# How far past the stated count the subject of a title usually sits. Titles
# read "Lot of 300+ Laptop AC Adapters - Lenovo, HP, ...": the subject is a
# short noun phrase right after the number, everything past the dash is
# elaboration. The minimum keeps a leading "- " from collapsing the window.
_SUBJECT_WINDOW = 60
_SUBJECT_MIN = 12


@dataclass
class Classification:
    """What we think the lot holds, and how sure we are."""
    item_class: str | None          # None means: do not price this lot
    family: str | None              # "computer" | "part"
    confidence: float               # 0-1, folded into the lot's confidence
    reason: str                     # shown in the UI, so it must read plainly
    candidates: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.item_class is not None

    def to_dict(self) -> dict:
        return {"item_class": self.item_class, "family": self.family,
                "confidence": self.confidence, "reason": self.reason,
                "candidates": list(self.candidates)}


def _subject_span(title: str) -> tuple[int, int]:
    m = re.search(r"\b(\d{1,4})\s*\+?\s*", title)
    start = m.end() if m else 0
    tail = title[start:start + _SUBJECT_WINDOW]
    cut = re.search(r"[–—(\[]|\s[-]\s|[.;:]", tail)
    end = cut.start() if cut else len(tail)
    return start, start + max(end, min(_SUBJECT_MIN, len(tail)))


def _hits(title: str) -> list[tuple[str, int, int]]:
    """Every class term in the title that names the subject, not a detail."""
    out = []
    for name, pat in _PATTERNS:
        for m in pat.finditer(title):
            before = title[max(0, m.start() - _ATTRIBUTE_LOOKBACK):m.start()]
            if _ATTRIBUTE_BEFORE.search(before):
                continue
            out.append((name, m.start(), m.end()))
    return sorted(out, key=lambda h: h[1])


def _narrowest(names) -> str:
    return min(names, key=lambda n: _SPECIFICITY[n])


def family_of(item_class: str | None) -> str | None:
    if item_class in COMPUTER_CLASSES:
        return "computer"
    if item_class in PART_CLASSES:
        return "part"
    return None


def _modifiers(title: str, hits) -> set[int]:
    """Hit indexes that are adjectives, not the thing being sold.

    In "computer monitors" and "desktop computers" the first term modifies
    the second. Counting it separately is what made "94 Desktop Computers"
    look like two items rather than one.
    """
    out = set()
    for i, (_, s0, e0) in enumerate(hits):
        for _, s1, _ in hits:
            if 0 <= s1 - e0 <= 12 and not title[e0 - 1:e0].lower() == "s":
                out.add(i)
                break
    return out


def _counted_classes(title: str, hits) -> set[str]:
    """Classes that carry their own count: "9 Monitors, 8 HP Desktops".

    A count attached to a term is the strongest evidence there is that the
    term names a thing being sold rather than describing one. Two of them,
    naming different things, is a mixed lot however tidy the title reads --
    and those were the lots poisoning the monitor comps with $47/unit
    pallets that were mostly desktops.
    """
    mods = _modifiers(title, hits)
    out = set()
    for i, (name, start, _) in enumerate(hits):
        if i in mods:
            continue
        if re.search(r"\b\d{1,4}\s*\)?\s*(?:[\w\"\'#-]+[\s/-]+){0,2}$",
                     title[:start]):
            out.add(name)
    return out


def _itemised(title: str, names: set[str], hits) -> bool:
    """A title that lists things from different families, each with a count.

    Restricted to cross-family lists on purpose: "29 Desktops and 15
    Laptops" is still a pallet of computers and the machine model prices it
    perfectly well. "94 Desktop Computers and 95 Computer Monitors" is two
    different markets in one pallet, and averaging them is meaningless.
    """
    if len({family_of(n) for n in names}) < 2:
        return False
    if len(_PAREN_COUNT.findall(title)) >= 2:
        return True
    return len(_counted_classes(title, hits)) >= 2


def _compound_head(title: str, hits) -> str | None:
    """A part sold under a computer adjective: "laptop AC adapters".

    The modifier has to be singular. English does not use a plural noun as
    an adjective, so "dell laptops monitors and towers" is three things
    being sold, not one -- and pricing it as monitors would be a guess
    dressed up as a reading.
    """
    found = None
    for name, start, _ in hits:
        if name not in PART_CLASSES:
            continue
        if re.search(r"\b(?:laptop|note\s*book|computer|desktop|pc|monitor|"
                     r"tablet|server)\s+$", title[:start], re.I):
            found = name if found is None else _narrowest({found, name})
    return found


def classify(title: str) -> Classification:
    """Decide what a lot holds. item_class=None means: do not price it."""
    t = (title or "").strip()
    if not t:
        return Classification(None, None, 0.0, "no title to read")

    hits = _hits(t)
    if not hits:
        return Classification(None, None, 0.0,
                              "nothing in the title names what this is")

    # Accessories FOR computers, named where the computer should be. The
    # same attribute rule applies: "**No Stand" says an all-in-one arrived
    # without its foot, not that the lot is a box of feet.
    lo0, hi0 = _subject_span(t)
    for m in _CONTAINER.finditer(t):
        if not (lo0 <= m.start() < hi0):
            continue
        before = t[max(0, m.start() - _ATTRIBUTE_LOOKBACK):m.start()]
        if _ATTRIBUTE_BEFORE.search(before):
            continue
        return Classification(None, None, 0.0,
                              "this looks like cases, stands or mounts rather "
                              "than the equipment itself")

    names = {n for n, _, _ in hits}
    cands = tuple(sorted(names))

    if _itemised(t, names, hits):
        return Classification(None, None, 0.0,
                              "the title itemises several different things",
                              cands)
    if _GRAB_BAG.search(t) and len(names) > 1:
        return Classification(None, None, 0.0,
                              "described as a mixed or assorted lot", cands)

    compound = _compound_head(t, hits)
    if compound:
        return Classification(
            compound, "part", 0.85,
            f"the title sells {compound}s, with the computer word describing "
            f"which kind", cands)

    # Three or more different things named and no compound head to explain
    # them: "LOT OF 25 (MONITORS, LAPTOPS, DESKTOPS, GPS AND HEAD SETS)".
    # Whatever this is, it is not one kind of thing.
    if len(names) >= 3:
        return Classification(None, None, 0.0,
                              "three or more different kinds of item named",
                              cands)

    comp = names & set(COMPUTER_CLASSES)
    part = names & set(PART_CLASSES)
    lo, hi = _subject_span(t)
    in_subject = {n for n, s, _ in hits if lo <= s < hi}
    # a term introduced by "and"/"," is one entry in a list, not the subject
    listed = {n for n, s, _ in hits if _LIST_ITEM_BEFORE.search(t[:s])}

    if comp and not part:
        cls = _narrowest((comp & in_subject) or comp)
        multi = len(comp) > 1
        return Classification(
            cls, "computer", 0.7 if multi else 0.9,
            "several kinds of computer, all priced by the machine model"
            if multi else f"the title names {cls}s and nothing else", cands)

    if part and not comp:
        if len(part) > 1:
            return Classification(
                None, None, 0.0,
                "several different kinds of part, with no way to tell how "
                "many of each", cands)
        return Classification(next(iter(part)), "part", 0.85,
                              f"the title names {next(iter(part))}s and "
                              f"nothing else", cands)

    # Both families named. Only the subject window can break the tie, and
    # only when the winner is not itself an item in a list.
    sub_comp = (in_subject & set(COMPUTER_CLASSES)) - listed
    sub_part = (in_subject & set(PART_CLASSES)) - listed
    if sub_comp and not sub_part:
        return Classification(_narrowest(sub_comp), "computer", 0.6,
                              "the lot is named as computers, with parts "
                              "mentioned alongside", cands)
    if sub_part and not sub_comp and len(sub_part) == 1:
        return Classification(next(iter(sub_part)), "part", 0.6,
                              "the lot is named as parts, with computers "
                              "mentioned alongside", cands)
    return Classification(None, None, 0.0,
                          "computers and parts both named, with no way to "
                          "tell which the lot mostly is", cands)
