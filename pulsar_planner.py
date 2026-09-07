#!/usr/bin/env python3
"""
pulsar_planner.py -- "what's up now?" for the DSES Spectrum Analyzer.

Answers the question the observing team actually asks at the dish: which
pulsars are above our horizon right now, how long do I have before this one
sets, and what are its catalog numbers (exact RA/Dec, P0, DM, flux)?

Two pieces:

  * `Catalog`  -- ATNF psrcat rows, fetched once over HTTP and CACHED on disk
    so the field boxes work offline afterwards. No psrqpy dependency: the
    ATNF web interface serves a plain-text table, which is a stable, tiny
    contract compared with pulling in a package (and its astroquery stack)
    onto a Raspberry Pi at a remote site.

  * `visible_now()` -- horizontal coordinates + time-above-mask for a site,
    using astropy when available and a self-contained fallback when it is
    not. The fallback is accurate to a few arcminutes, which is far below
    the beamwidth of any DSES dish, so a missing astropy degrades the
    planner's precision imperceptibly rather than disabling it.

Flux handling follows the tuned band: DSES records anywhere from 0.1-2 GHz,
so the caller passes the current center frequency and gets the nearest
available S400/S1400 column rather than a hardcoded one. Magnetars (psrcat
TYPE AXP/SGR) are carried through even though their flux fields are usually
empty -- a flux filter must never silently hide them.
"""
from __future__ import annotations

import json
import math
import re
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ATNF psrcat web query. `table_bottom.txt` style plain output; we ask for
# the columns we need and parse the fixed table it returns.
# ATNF psrcat web query. "Short without errors" is the key: the default
# styles interleave per-value error digits and HTML reference links with the
# data, while this one returns a clean fixed-column table. Parameter names
# are case-sensitive (JName, RaJ, DecJ...), not the psrcat field names.
ATNF_URL = (
    "https://www.atnf.csiro.au/research/pulsar/psrcat/proc_form.php"
    "?version=LATEST&JName=JName&BName=BName&RaJ=RaJ&DecJ=DecJ&P0=P0&DM=DM"
    "&S400=S400&S1400=S1400&W50=W50&Type=Type&startUserDefined=true"
    "&c1_val=&c2_val=&c3_val=&c4_val=&sort_attr=jname&sort_order=asc"
    "&condition=&ephemeris=short&coords_unit=raj%2Fdecj&radius="
    "&coords_1=&coords_2=&style=Short+without+errors&no_value=*"
    "&fsize=3&x_axis=&x_scale=linear&y_axis=&y_scale=linear&state=query"
    "&table_bottom.x=30&table_bottom.y=22")

CACHE_NAME = "atnf_psrcat_cache.json"
CACHE_MAX_AGE_DAYS = 90          # catalog changes slowly; refresh seasonally
CACHE_FMT = 2                    # 2 = rows carry w50_ms (2026-09); a cache
                                 # without it is refetched when online, but
                                 # still works offline (w50 degrades to the
                                 # 5% duty-cycle assumption).



# --------------------------------------------------------------------------
# coordinate helpers (no hard astropy dependency)
# --------------------------------------------------------------------------

def _sex_to_deg(text, is_ra):
    """'03:32:59.37' -> degrees. RA is hours, Dec is degrees."""
    if not text or text.strip() in ("*", ""):
        return None
    s = text.strip()
    neg = s.startswith("-")
    s = s.lstrip("+-")
    parts = (s.split(":") + ["0", "0"])[:3]
    try:
        v = abs(float(parts[0])) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0
    except ValueError:
        return None
    if is_ra:
        v *= 15.0
    return -v if neg else v


def _sigproc_packed(text, is_ra):
    """'03:32:59.37' -> 33259.37 (SIGPROC packed sexagesimal), sign kept."""
    if not text or text.strip() in ("*", ""):
        return 0.0
    s = text.strip()
    neg = s.startswith("-")
    s = s.lstrip("+-")
    p = (s.split(":") + ["0", "0"])[:3]
    try:
        v = abs(float(p[0])) * 1e4 + float(p[1]) * 1e2 + float(p[2])
    except ValueError:
        return 0.0
    return -v if neg else v


def _julian_day(unix_ts):
    return unix_ts / 86400.0 + 2440587.5


def _gmst_deg(unix_ts):
    """Greenwich mean sidereal time in degrees (IAU 1982 series)."""
    jd = _julian_day(unix_ts)
    d = jd - 2451545.0
    t = d / 36525.0
    gmst = (280.46061837 + 360.98564736629 * d
            + 0.000387933 * t * t - t * t * t / 38710000.0)
    return gmst % 360.0


def altaz(ra_deg, dec_deg, lat_deg, lon_deg, unix_ts):
    """(altitude, azimuth) in degrees. Mean coordinates, no refraction —
    accurate to a few arcminutes, far inside any DSES beam."""
    lst = (_gmst_deg(unix_ts) + lon_deg) % 360.0
    ha = math.radians((lst - ra_deg) % 360.0)
    dec = math.radians(dec_deg)
    lat = math.radians(lat_deg)
    sin_alt = (math.sin(dec) * math.sin(lat)
               + math.cos(dec) * math.cos(lat) * math.cos(ha))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)
    cos_alt = math.cos(alt)
    if abs(cos_alt) < 1e-9:
        az = 0.0
    else:
        cos_az = ((math.sin(dec) - math.sin(alt) * math.sin(lat))
                  / (cos_alt * math.cos(lat)))
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        if math.sin(ha) > 0:
            az = 360.0 - az
    return math.degrees(alt), az % 360.0


def altaz_batch(ra_list, dec_list, lat_deg, lon_deg, unix_ts, height_m=0.0):
    """Alt/az for many sources at one instant.

    Uses astropy when importable — it applies precession, nutation and
    aberration, which the closed form below does not; measured against it,
    the fallback runs ~15' high in altitude. That is a third of the 60-ft
    dish's L-band beam: irrelevant for "is it up and for how long", which is
    all the planner claims, but there is no reason to accept it when the
    better answer is one import away. Vectorized so a 3000-row catalog costs
    one transform rather than 3000.
    """
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        import astropy.units as u
        loc = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg,
                            height=height_m * u.m)
        frame = AltAz(obstime=Time(unix_ts, format="unix"), location=loc)
        sc = SkyCoord(ra=ra_list * u.deg, dec=dec_list * u.deg).transform_to(frame)
        return list(sc.alt.deg), list(sc.az.deg)
    except Exception:
        out_alt, out_az = [], []
        for ra, dec in zip(ra_list, dec_list):
            a, z = altaz(ra, dec, lat_deg, lon_deg, unix_ts)
            out_alt.append(a)
            out_az.append(z)
        return out_alt, out_az


def hours_above_mask(ra_deg, dec_deg, lat_deg, lon_deg, unix_ts, mask_deg,
                     horizon_hours=24.0, step_min=2.0):
    """Hours until the source next drops below `mask_deg`.

    Stepped search rather than a closed form: it handles circumpolar
    sources (returns horizon_hours), sources already below the mask
    (returns 0.0), and the elevation mask itself without special cases.
    """
    alt0, _ = altaz(ra_deg, dec_deg, lat_deg, lon_deg, unix_ts)
    if alt0 < mask_deg:
        return 0.0
    step = step_min * 60.0
    n = int(horizon_hours * 3600.0 / step)
    for i in range(1, n + 1):
        alt, _ = altaz(ra_deg, dec_deg, lat_deg, lon_deg, unix_ts + i * step)
        if alt < mask_deg:
            # linear interpolation inside the last step
            prev_alt, _ = altaz(ra_deg, dec_deg, lat_deg, lon_deg,
                                unix_ts + (i - 1) * step)
            frac = ((prev_alt - mask_deg) / (prev_alt - alt)
                    if prev_alt != alt else 0.0)
            return ((i - 1) + max(0.0, min(1.0, frac))) * step / 3600.0
    return horizon_hours          # circumpolar (or never sets within a day)


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------

class Catalog:
    """ATNF psrcat rows with a local cache.

    `rows` is a list of dicts: name, bname, ra_deg, dec_deg, raj/decj
    (SIGPROC packed), p0_s, dm, s400, s1400, w50_ms, type.
    """

    def __init__(self, cache_dir=None):
        self.cache_path = Path(cache_dir or Path.home() /
                               "Documents" / "DSES_SA_Recordings") / CACHE_NAME
        self.rows = []
        self.source = "none"       # 'cache' | 'network' | 'none'
        self.error = ""

    # -- cache ------------------------------------------------------------
    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                blob = json.load(f)
            age_days = (time.time() - blob.get("fetched", 0)) / 86400.0
            self.rows = blob.get("rows", [])
            self.source = "cache"
            self._cache_fmt = blob.get("fmt", 1)
            return bool(self.rows), age_days
        except Exception:
            self._cache_fmt = 0
            return False, 0.0

    def _save_cache(self):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({"fetched": time.time(), "fmt": CACHE_FMT,
                           "rows": self.rows}, f)
        except OSError:
            pass                    # cache is an optimization, never fatal

    # -- fetch ------------------------------------------------------------
    def load(self, force_refresh=False, timeout=30):
        """Cache first (so the field works offline), network only when the
        cache is missing, stale, outdated in format, or a refresh is
        demanded. A pre-W50 cache still serves offline."""
        ok, age = self._load_cache()
        if (ok and not force_refresh and age < CACHE_MAX_AGE_DAYS
                and self._cache_fmt >= CACHE_FMT):
            return True
        try:
            rows = self._fetch()
            if rows:
                self.rows = rows
                self.source = "network"
                self._save_cache()
                return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        return bool(self.rows)      # fall back on a stale cache if present

    def _fetch(self, timeout=30):
        req = urllib.request.Request(
            ATNF_URL, headers={"User-Agent": "DSES-Spectrum-Analyzer/1.2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return self._parse(text)

    @staticmethod
    def _parse(text):
        """Parse the psrcat table.

        Columns (Short without errors):
            #  PSRJ  PSRB  RAJ  DECJ  P0  DM  S400  S1400  W50  PSRTYPE
        Values are whitespace-separated with '*' for missing. TYPE may carry
        a bracketed reference ("HE[wcp+18]") which is stripped.
        """
        body = text[text.find("<pre>"):] if "<pre>" in text else text
        body = re.sub(r"<[^>]+>", "", body).replace("&nbsp", " ")
        rows = []
        for line in body.splitlines():
            toks = line.split()
            if len(toks) < 10 or not toks[0].isdigit():
                continue                      # header, rule, or blank
            (_, jname, bname, raj_s, decj_s, p0, dm, s400, s1400,
             w50) = toks[:10]
            ptype = toks[10] if len(toks) > 10 else "*"
            ra = _sex_to_deg(raj_s, True)
            dec = _sex_to_deg(decj_s, False)
            if ra is None or dec is None:
                continue                      # no position: unusable here

            def num(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            rows.append({
                "name": jname,
                "bname": bname,
                "ra_deg": ra, "dec_deg": dec,
                "raj": _sigproc_packed(raj_s, True),
                "decj": _sigproc_packed(decj_s, False),
                "p0_s": num(p0), "dm": num(dm),
                "s400": num(s400), "s1400": num(s1400),
                "w50_ms": num(w50),
                "type": re.sub(r"\[[^\]]*\]", "", ptype),
            })
        return rows


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------

def flux_for_freq(row, center_hz):
    """(value_mJy, label) nearest the tuned band — S400 below ~900 MHz,
    S1400 above, falling back to whichever exists. Magnetars usually have
    neither; they still belong in the list."""
    s400, s1400 = row.get("s400"), row.get("s1400")
    prefer_400 = (center_hz or 1.4e9) < 900e6
    order = ((s400, "S400"), (s1400, "S1400")) if prefer_400 else \
            ((s1400, "S1400"), (s400, "S400"))
    for v, label in order:
        if v is not None:
            return v, label
    return None, "—"


def is_magnetar(row):
    t = (row.get("type") or "").upper()
    return "AXP" in t or "SGR" in t


def flux_at_freq(row, center_hz):
    """Power-law flux estimate AT the tuned frequency, from the catalog's
    S400/S1400 anchors.

    Both anchors present → the source's own spectral index; one anchor →
    a typical pulsar index of −1.6. Returns (mJy, label) or (None, "—").
    An estimate, plainly labeled as one: real pulsar spectra turn over
    below a few hundred MHz and scintillate everywhere.
    """
    s400, s1400 = row.get("s400"), row.get("s1400")
    f_mhz = (center_hz or 1.4e9) / 1e6
    if s400 and s1400 and s400 > 0 and s1400 > 0:
        alpha = math.log(s1400 / s400) / math.log(1400.0 / 400.0)
        val = s1400 * (f_mhz / 1400.0) ** alpha
    elif s1400 and s1400 > 0:
        val = s1400 * (f_mhz / 1400.0) ** -1.6
    elif s400 and s400 > 0:
        val = s400 * (f_mhz / 400.0) ** -1.6
    else:
        return None, "—"
    return val, f"est@{f_mhz:.0f}"


def min_duration_s(flux_mjy, p0_s, sefd_jy, bw_hz,
                   n_sigma=8.0, duty=0.05, n_pol=1, w50_ms=None):
    """Radiometer minimum integration (seconds) for an `n_sigma` folded
    detection of a pulsar with period-averaged flux `flux_mjy`.

    Folded S/N = (S/SEFD) · sqrt(n_pol·BW·T) · sqrt((P−W)/W), inverted
    for T. W comes from the catalog W50 when available; otherwise `duty`·P
    (5% is a typical slow-pulsar duty cycle). P is required either way so
    sources with no catalog period honestly return None instead of a
    number. This is an aid, not a gate: a single SEFD serves every band,
    and the real sky adds RFI, scintillation, and pointing loss on top.
    """
    if not flux_mjy or flux_mjy <= 0 or not p0_s or p0_s <= 0:
        return None
    if not sefd_jy or sefd_jy <= 0 or not bw_hz or bw_hz <= 0:
        return None
    if w50_ms and 0.0 < w50_ms / 1000.0 < p0_s:
        duty = (w50_ms / 1000.0) / p0_s
    duty = min(max(duty, 1e-4), 0.9)
    s_jy = flux_mjy / 1000.0
    return ((n_sigma * sefd_jy / s_jy) ** 2
            * (duty / (1.0 - duty)) / (n_pol * bw_hz))


def visible_now(rows, lat_deg, lon_deg, mask_deg=2.0, unix_ts=None,
                center_hz=1.4e9, min_flux_mjy=None, include_magnetars=True,
                height_m=0.0, include_below=False):
    """Rows currently above `mask_deg`, annotated and sorted by flux
    (brightest first), then by time remaining.

    A flux floor never hides magnetars or anything else with no flux value
    in the catalog when include_magnetars is on — silence in the catalog is
    not the same as a faint source.
    """
    ts = time.time() if unix_ts is None else unix_ts
    if not rows:
        return []
    alts, azs = altaz_batch([r["ra_deg"] for r in rows],
                            [r["dec_deg"] for r in rows],
                            lat_deg, lon_deg, ts, height_m)
    out = []
    for r, alt, az in zip(rows, alts, azs):
        below = alt < mask_deg
        if below and not include_below:
            continue
        flux, flux_label = flux_for_freq(r, center_hz)
        mag = is_magnetar(r)
        if min_flux_mjy is not None and flux is not None and flux < min_flux_mjy:
            if not (mag and include_magnetars):
                continue
        if mag and not include_magnetars:
            continue
        item = dict(r)
        item.update({
            "alt_deg": alt, "az_deg": az,
            "flux_mjy": flux, "flux_label": flux_label,
            "magnetar": mag, "below_mask": below,
        })
        if below:
            # Not up now: say when it will be, and for how long.
            rise_h, span_h = next_window(r["ra_deg"], r["dec_deg"],
                                         lat_deg, lon_deg, ts, mask_deg)
            item["hours_left"] = 0.0
            item["rise_in_h"] = rise_h
            item["window_h"] = span_h
        else:
            item["hours_left"] = hours_above_mask(
                r["ra_deg"], r["dec_deg"], lat_deg, lon_deg, ts, mask_deg)
            item["rise_in_h"] = 0.0
            item["window_h"] = item["hours_left"]
        out.append(item)
    # Up-now first, then brightest, then most time remaining.
    out.sort(key=lambda d: (d["below_mask"],
                            -(d["flux_mjy"] or -1.0),
                            -d["hours_left"]))
    return out


def next_window(ra_deg, dec_deg, lat_deg, lon_deg, unix_ts, mask_deg,
                horizon_hours=24.0, step_min=5.0):
    """(hours_until_rise, hours_of_window) for a source below the mask.

    Answers "when can I record this, and for how long?" — the question a
    planner that only reports what is up right now cannot (Rick,
    2026-08-04: B0329+54 is circumpolar from Haswell yet spends part of
    each day below a usable elevation). Returns (None, 0.0) if the source
    never clears the mask within the search horizon.
    """
    step = step_min * 60.0
    n = int(horizon_hours * 3600.0 / step)
    rise_i = None
    for i in range(0, n + 1):
        alt, _ = altaz(ra_deg, dec_deg, lat_deg, lon_deg, unix_ts + i * step)
        if alt >= mask_deg:
            rise_i = i
            break
    if rise_i is None:
        return None, 0.0
    rise_ts = unix_ts + rise_i * step
    # Length of the window that starts there (nudged inside to avoid
    # landing exactly on the boundary).
    span = hours_above_mask(ra_deg, dec_deg, lat_deg, lon_deg,
                            rise_ts + step, mask_deg,
                            horizon_hours=horizon_hours, step_min=step_min)
    return rise_i * step / 3600.0, span + step / 3600.0


def sets_before(row, lat_deg, lon_deg, mask_deg, duration_s, unix_ts=None):
    """(will_set, hours_left) — does this source drop below the mask before
    a recording of `duration_s` finishes?"""
    ts = time.time() if unix_ts is None else unix_ts
    left = hours_above_mask(row["ra_deg"], row["dec_deg"], lat_deg, lon_deg,
                            ts, mask_deg)
    return (left * 3600.0 < duration_s), left


def find_by_name(rows, name):
    """Catalog row for a J or B designation, case/space-insensitive."""
    if not name:
        return None
    key = name.strip().upper().replace(" ", "")
    for r in rows:
        if r["name"].upper() == key or (r.get("bname", "*").upper() == key):
            return r
    return None
