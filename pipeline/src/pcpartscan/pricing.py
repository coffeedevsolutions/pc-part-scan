"""Machine valuation from four independent sources.

The two GovDeals-derived models are the backbone, and they map directly onto
the floor/ceiling framing:

  BasketModel  - fitted on sold BULK lots. Answers "what does a pallet of these
                 actually clear at auction?" -> the resale-as-lot FLOOR.
  SingleModel  - fitted on sold SINGLE machines. Answers "what does one of these
                 clear when listed by itself?" -> the parts-out CEILING.

Two things refine the ceiling:

  PinnedModel  - the single-unit fit with hand-pinned CPU prices substituted
                 per machine. A pin is an override, not a rival estimate.
  EbayAdapter  - official eBay API, a genuinely independent second opinion.
                 Requires your own credentials; see the class docstring. eBay
                 actively blocks scraping, so there is no scrape fallback.

Both models are ridge-regularized least squares over the same feature space,
with negative coefficients clamped (a faster CPU never subtracts value).
"""

from __future__ import annotations

import csv
import json
import os

import numpy as np

from . import specs

CACHE = "cache"
MIN_CPU_OBS = 4          # below this a CPU falls back to its generation bucket
RIDGE = 1.0


# --------------------------------------------------------------- feature space

def _cpu_tier(cpu: str | None) -> str:
    if not cpu:
        return "unknown"
    if cpu.startswith("i9"):
        return "i9"
    if cpu.startswith("i7"):
        return "i7"
    if cpu.startswith("i5"):
        return "i5"
    if cpu.startswith("i3"):
        return "i3"
    if cpu.startswith(("e5", "e3", "w-")):
        return "xeon"
    if cpu.startswith("ryzen"):
        return "ryzen"
    return "other"


def _bucket(cpu: str | None) -> str:
    """Coarse fallback identity for a CPU we have too few observations of."""
    g = specs.cpu_generation(cpu or "")
    return f"{_cpu_tier(cpu)}-gen{g}" if g else _cpu_tier(cpu)


class FeatureSpace:
    def __init__(self, machines: list[dict]):
        counts: dict[str, int] = {}
        for m in machines:
            if m.get("cpu"):
                counts[m["cpu"]] = counts.get(m["cpu"], 0) + 1
        self.cpus = sorted(c for c, n in counts.items() if n >= MIN_CPU_OBS)
        self.buckets = sorted({_bucket(m.get("cpu")) for m in machines})
        self.forms = sorted({m.get("form_factor") or "unknown" for m in machines})
        self.names = (
            [f"cpu={c}" for c in self.cpus]
            + [f"bucket={b}" for b in self.buckets]
            + [f"form={f}" for f in self.forms]
            + ["ram_gb", "has_drive"]
        )
        # No explicit intercept: every machine activates exactly one bucket
        # dummy, so the buckets already play that role. Adding an intercept on
        # top makes the design collinear, and under ridge + non-negativity the
        # intercept absorbs the mean while every CPU coefficient is clamped to
        # zero -- which collapsed all i5s to one identical price.

    def __len__(self):
        return len(self.names)

    def vec(self, m: dict) -> np.ndarray:
        x = np.zeros(len(self))
        o = 0
        cpu = m.get("cpu")
        if cpu in self.cpus:
            x[o + self.cpus.index(cpu)] = 1.0
        o += len(self.cpus)
        b = _bucket(cpu)
        if b in self.buckets:
            x[o + self.buckets.index(b)] = 1.0
        o += len(self.buckets)
        f = m.get("form_factor") or "unknown"
        if f in self.forms:
            x[o + self.forms.index(f)] = 1.0
        o += len(self.forms)
        x[o] = (m.get("ram_gb") or 0) / 8.0     # in 8GB units
        x[o + 1] = 1.0 if m.get("has_drive") else 0.0
        return x


# ---------------------------------------------------------------------- models

class _FitModel:
    def __init__(self, space: FeatureSpace, coef: np.ndarray, n_obs: int, r2: float):
        self.space, self.coef, self.n_obs, self.r2 = space, coef, n_obs, r2

    def value(self, machine: dict) -> float:
        return float(max(0.0, self.space.vec(machine) @ self.coef))

    def value_mix(self, mix: list[dict]) -> float:
        return float(sum(self.value(m) * m.get("qty", 1) for m in mix))

    def to_json(self):
        return {"names": self.space.names, "coef": self.coef.tolist(),
                "n_obs": self.n_obs, "r2": self.r2,
                "cpus": self.space.cpus, "buckets": self.space.buckets,
                "forms": self.space.forms}


def _solve(X: np.ndarray, y: np.ndarray, ridge: float = RIDGE) -> np.ndarray:
    """Ridge least squares with a non-negativity clamp-and-refit pass."""
    n = X.shape[1]
    A = X.T @ X + ridge * np.eye(n)
    coef = np.linalg.solve(A, X.T @ y)
    # clamp negatives and refit the survivors -- crude NNLS, adequate here and
    # avoids pulling in scipy
    for _ in range(25):
        neg = coef < 0
        if not neg.any():
            break
        keep = ~neg
        coef = np.zeros(n)
        if keep.sum() == 0:
            break
        Xk = X[:, keep]
        Ak = Xk.T @ Xk + ridge * np.eye(keep.sum())
        coef[keep] = np.linalg.solve(Ak, Xk.T @ y)
    # guarantee the invariant even if the active set did not converge:
    # no feature may subtract value from a machine
    coef[coef < 0] = 0.0
    return coef


def _r2(X, y, coef):
    pred = X @ coef
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def _robust_fit(X, y, ridge=RIDGE, trim=0.08, rounds=3):
    """Least squares with iterative trimming of the worst residuals.

    A handful of mislabeled lots (a pallet described as one machine, a machine
    bundled with a monitor) otherwise dominate the fit.
    """
    keep = np.ones(len(y), dtype=bool)
    coef = _solve(X, y, ridge)
    for _ in range(rounds):
        resid = np.abs(y - X @ coef)
        cut = np.quantile(resid[keep], 1 - trim)
        new_keep = resid <= max(cut, 1e-9)
        if new_keep.sum() < max(20, 0.5 * len(y)) or (new_keep == keep).all():
            break
        keep = new_keep
        coef = _solve(X[keep], y[keep], ridge)
    return coef, keep


def fit_single_model(singles: list[dict]) -> _FitModel:
    """Per-machine value from sold single-unit lots -> the parts-out ceiling.

    Sanity-bounded: a lone used business desktop that "sold" for $5,000 is a
    mislabeled pallet, not a data point.
    """
    clean = [s for s in singles if 10.0 <= s["price"] <= 1500.0]
    machines = [s["machine"] for s in clean]
    space = FeatureSpace(machines)
    X = np.array([space.vec(m) for m in machines])
    y = np.array([s["price"] for s in clean], dtype=float)
    coef, keep = _robust_fit(X, y)
    return _FitModel(space, coef, int(keep.sum()), _r2(X[keep], y[keep], coef))


class PinnedModel:
    """The fitted single-unit model with hand-pinned CPU prices substituted.

    A pin means "for this CPU, use my number instead of yours", so it is
    applied per machine rather than offered as a rival estimate to be
    averaged in. Blending it as a separate source meant a pin only counted
    when it happened to cover most of a lot, which is not what pinning a
    price means -- and left every un-pinned attribute of that source, RAM
    included, valued at zero.

    Everything not pinned -- the RAM and drive adders, every other CPU --
    still comes from the fit. Attribute access falls through to the base
    model so this stands in for it wherever a fit is expected.
    """

    def __init__(self, base: _FitModel, pins: dict[str, float]):
        self.base = base
        self.cpu_pins = {k: float(v) for k, v in pins.items()
                         if k != "_ram_per_8gb"}
        if "_ram_per_8gb" in pins:
            self.ram_per_8gb = float(pins["_ram_per_8gb"])
        else:
            names = base.space.names
            self.ram_per_8gb = float(base.coef[names.index("ram_gb")])

    def __getattr__(self, name):
        # r2, n_obs, space, coef, to_json() -- the fit is still the fit
        return getattr(self.base, name)

    def value(self, machine: dict) -> float:
        cpu = machine.get("cpu")
        if cpu in self.cpu_pins:
            ram_units = (machine.get("ram_gb") or 0) / 8.0
            return max(0.0, self.cpu_pins[cpu] + self.ram_per_8gb * ram_units)
        return self.base.value(machine)

    def value_mix(self, mix: list[dict]) -> float:
        return float(sum(self.value(m) * m.get("qty", 1) for m in mix))

    def pins_applied(self, mix: list[dict]) -> int:
        """Units in this mix whose price came from a pin."""
        return sum(m.get("qty", 1) for m in mix
                   if m.get("cpu") in self.cpu_pins)


class BulkDiscountModel:
    """How far below parts-out value a bulk lot actually clears.

    Fitting a full per-CPU model on bulk lots does not work: there are only a
    few dozen lots with reconcilable manifests against ~45 features, which is
    hopelessly underdetermined (it produced R^2 = -57 and per-unit bulk values
    above per-unit single values, which is nonsense).

    So this fits ONE parameter instead:

        lot_price ~= k * sum(qty_i * single_value_i)

    k is the bulk discount -- the share of parts-out value a pallet clears at
    auction. One parameter against dozens of observations is well-determined,
    and k is directly interpretable.
    """

    # Below these the fit is not telling us anything: a non-positive R^2 means
    # the model predicts worse than the corpus mean, and a handful of lots
    # cannot pin down a market-wide discount. The floor is then reported but
    # not underwritten against -- see grade.value_lot.
    MIN_R2 = 0.05
    MIN_OBS = 20

    def __init__(self, single: _FitModel, k: float, n_obs: int, r2: float,
                 residual_sd: float):
        self.single, self.k, self.n_obs = single, k, n_obs
        self.r2, self.residual_sd = r2, residual_sd

    @property
    def trusted(self) -> bool:
        """Is this fit good enough to set a bid ceiling from?"""
        return self.r2 >= self.MIN_R2 and self.n_obs >= self.MIN_OBS

    def value_mix(self, mix: list[dict]) -> float:
        return self.k * self.single.value_mix(mix)

    def value(self, machine: dict) -> float:
        return self.k * self.single.value(machine)

    def to_json(self):
        return {"kind": "bulk_discount", "k": self.k, "n_obs": self.n_obs,
                "r2": self.r2, "residual_sd": self.residual_sd,
                "trusted": self.trusted}


def fit_basket_model(baskets: list[dict], single: _FitModel) -> BulkDiscountModel:
    """Fit the bulk discount k on lots whose manifest reconciles."""
    usable = [b for b in baskets if b.get("exact") and b["mix"]]
    if len(usable) < 8:
        raise ValueError(f"only {len(usable)} exact-manifest lots; need >= 8")
    x = np.array([single.value_mix(b["mix"]) for b in usable])
    y = np.array([b["price"] for b in usable], dtype=float)
    ok = x > 0
    x, y = x[ok], y[ok]
    if len(x) < 8:
        raise ValueError(f"only {len(x)} lots priceable by the single model")

    # ratio-of-medians is far more robust here than OLS through the origin,
    # which a couple of huge pallets would otherwise dominate
    ratios = np.sort(y / x)
    k = float(np.median(ratios))
    pred = k * x
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return BulkDiscountModel(single, k, len(x), r2,
                             float(np.std(ratios, ddof=1)) if len(ratios) > 1 else 0.0)


# ---------------------------------------------------------------- static table

class StaticTable:
    """Hand-maintained CSV override: cpu,value_usd. Seeded from a fitted model.

    Anything present here wins over the fitted estimate, so you can pin prices
    you have direct knowledge of.
    """

    # lives in the tracked dataset, not the scratch cache -- hand edits to
    # this file are durable and are meant to be committed
    PATH = os.path.join(os.environ.get("PCPS_DATA", "data"),
                        "component_prices.csv")

    def __init__(self, path: str | None = None):
        self.path = path or self.PATH
        self.cpu_value: dict[str, float] = {}
        self.ram_per_8gb = 0.0
        if os.path.exists(self.path):
            with open(self.path, newline="") as f:
                for row in csv.DictReader(f):
                    k, v = row["key"].strip(), float(row["value_usd"])
                    if k == "_ram_per_8gb":
                        self.ram_per_8gb = v
                    else:
                        self.cpu_value[k] = v

    def as_pins(self) -> dict[str, float]:
        """This table expressed as per-CPU pins for PinnedModel."""
        pins = dict(self.cpu_value)
        if self.ram_per_8gb:
            pins["_ram_per_8gb"] = self.ram_per_8gb
        return pins

    def value(self, machine: dict) -> float | None:
        cpu = machine.get("cpu")
        if cpu not in self.cpu_value:
            return None
        return self.cpu_value[cpu] + self.ram_per_8gb * ((machine.get("ram_gb") or 0) / 8.0)

    @classmethod
    def seed_from(cls, model: _FitModel, path: str | None = None) -> str:
        """Write a starter CSV from a fitted model so it is editable, not guessed."""
        path = path or cls.PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        names, coef = model.space.names, model.coef
        ram = float(coef[names.index("ram_gb")])
        rows = []
        for cpu in model.space.cpus:
            base = model.value({"cpu": cpu, "ram_gb": 0, "form_factor": None,
                                "has_drive": False})
            rows.append((cpu, round(base, 2)))
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["key", "value_usd", "note"])
            w.writerow(["_ram_per_8gb", round(ram, 2), "added per 8GB of RAM"])
            for cpu, v in sorted(rows):
                w.writerow([cpu, v, "seeded from fitted single-unit model"])
        return path


# ------------------------------------------------------------------ eBay (API)

class EbayAdapter:
    """Official eBay Browse API adapter. Disabled unless you supply credentials.

    eBay serves a human-verification challenge to non-browser clients AND to
    automated browsers, so there is deliberately no HTML-scraping path here.
    The supported route is the official API:

      1. Create an app at https://developer.ebay.com -> get App ID + Cert ID.
      2. export EBAY_CLIENT_ID=...  EBAY_CLIENT_SECRET=...

    What this can and cannot see matters to how its numbers are used.
    Marketplace Insights, which serves true SOLD prices, is heavily
    restricted and we are not getting access to it. So the only eBay figure
    available is the Browse API's ACTIVE listing price: what sellers are
    ASKING, not what anything fetched. Asks run above realized prices --
    that is why the listing is still up -- and feeding one into the ceiling
    unadjusted would inflate every lot it touched.

    So an ask is converted to an expected realized price by a haircut that
    is MEASURED rather than assumed. We already hold thousands of realized
    single-unit GovDeals prices; `calibrate()` pairs them against eBay asks
    for the same CPU and takes the median ratio. Until enough pairs exist to
    measure it, the adapter reports nothing and the grader drops the source
    -- an unmeasured haircut is a number someone made up, and this system
    already has one bad experience with those.

    Without credentials every call returns None and the grader simply drops
    this source from the blend.
    """

    TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    MAX_CONSECUTIVE_FAILURES = 3   # circuit breaker: stop calling for the run
    CALL_TIMEOUT = 10              # seconds; a degraded API must not stall a scan

    # Pairs of (eBay ask, GovDeals realized) for the same CPU needed before
    # the haircut is trusted. Below this the source is silent.
    MIN_CALIBRATION_PAIRS = 12
    # Sanity bounds on the measured ratio. An ask below the realized price or
    # more than five times it means the query matched the wrong thing, not
    # that the market moved.
    RATIO_BOUNDS = (0.05, 1.0)

    def __init__(self):
        self.cid = os.environ.get("EBAY_CLIENT_ID")
        self.secret = os.environ.get("EBAY_CLIENT_SECRET")
        self._token = None
        self._memo: dict[tuple, float | None] = {}
        self._consecutive_failures = 0
        self.enabled = bool(self.cid and self.secret)
        # None until calibrate() succeeds; the adapter stays silent until then
        self.haircut: float | None = None
        self.haircut_n = 0

    def _auth(self) -> str | None:
        if not self.enabled:
            return None
        if self._token:
            return self._token
        import base64, urllib.parse, urllib.request
        b = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }).encode()
        req = urllib.request.Request(
            self.TOKEN_URL, data=data,
            headers={"Authorization": f"Basic {b}",
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as r:
            self._token = json.loads(r.read())["access_token"]
        return self._token

    def ask(self, machine: dict) -> float | None:
        """Median ACTIVE listing price for this machine. An ask, not a sale.

        Memoized per (cpu, ram) for the life of the adapter: the same CPU
        appears across many machines and lots, and re-querying it would turn
        one scan into hundreds of sequential HTTP calls. A few consecutive
        failures trip a circuit breaker so a degraded eBay API cannot stall
        a scheduled scan into its job timeout.
        """
        cpu = machine.get("cpu")
        if not cpu:
            return None
        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            return None
        memo_key = (cpu, machine.get("ram_gb") or 0)
        if memo_key in self._memo:
            return self._memo[memo_key]
        try:
            tok = self._auth()
        except Exception:
            self._consecutive_failures += 1
            return None
        if not tok:
            return None
        import urllib.parse, urllib.request
        q = f"desktop computer {cpu} {machine.get('ram_gb') or ''}GB".strip()
        url = self.BROWSE_URL + "?" + urllib.parse.urlencode(
            {"q": q, "limit": "50", "category_ids": "179"})  # PC Desktops
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {tok}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        try:
            with urllib.request.urlopen(req, timeout=self.CALL_TIMEOUT) as r:
                data = json.loads(r.read())
        except Exception:
            self._consecutive_failures += 1
            self._memo[memo_key] = None
            return None
        self._consecutive_failures = 0
        prices = []
        for it in data.get("itemSummaries") or []:
            p = (it.get("price") or {}).get("value")
            if p:
                prices.append(float(p))
        result = sorted(prices)[len(prices) // 2] if prices else None
        self._memo[memo_key] = result
        return result

    def calibrate(self, singles: list[dict]) -> float | None:
        """Measure the ask-to-realized haircut against sold GovDeals singles.

        `singles` are the same priced single-unit observations the machine
        model is fitted on: a known machine and what it actually fetched.
        Asking the Browse API what the same CPU is listed at gives one pair
        per CPU, and the median of those ratios is the haircut.

        Returns the ratio, or None when there are too few pairs to measure
        one -- in which case the adapter stays silent rather than guessing.
        """
        if not self.enabled:
            return None
        realized: dict[str, list[float]] = {}
        for s in singles:
            cpu = (s.get("machine") or {}).get("cpu")
            price = s.get("price")
            if cpu and price and 10.0 <= price <= 1500.0:
                realized.setdefault(cpu, []).append(float(price))
        ratios = []
        for cpu, prices in realized.items():
            if len(prices) < 2:
                continue          # one sale is an anecdote, not a comp
            asked = self.ask({"cpu": cpu})
            if not asked or asked <= 0:
                continue
            got = sorted(prices)[len(prices) // 2]
            r = got / asked
            if self.RATIO_BOUNDS[0] <= r <= self.RATIO_BOUNDS[1]:
                ratios.append(r)
        if len(ratios) < self.MIN_CALIBRATION_PAIRS:
            self.haircut, self.haircut_n = None, len(ratios)
            return None
        self.haircut = sorted(ratios)[len(ratios) // 2]
        self.haircut_n = len(ratios)
        return self.haircut

    def value(self, machine: dict) -> float | None:
        """Expected realized price: the eBay ask with the measured haircut.

        None whenever the haircut has not been measured, which keeps an
        unadjusted asking price out of the ceiling by construction.
        """
        if self.haircut is None:
            return None
        asked = self.ask(machine)
        return asked * self.haircut if asked else None

    def to_json(self) -> dict:
        return {"enabled": self.enabled, "haircut": self.haircut,
                "haircut_pairs": self.haircut_n}


# ------------------------------------------------------------------- persistence

def save_models(single: _FitModel, basket: _FitModel | None):
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "models.json"), "w") as f:
        json.dump({"single": single.to_json(),
                   "bulk": basket.to_json() if basket else None}, f, indent=1)
