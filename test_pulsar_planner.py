#!/usr/bin/env python3
"""Tests for pulsar_planner.py — catalog parsing, coordinates, planning.

Network is used only by the optional last test; everything else runs from a
synthetic table so the suite works at the dish with no internet.
"""
import math
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pulsar_planner as pp

LAT, LON, AMSL = 38.3808, -103.156, 1340.0      # DSES Haswell
FAILURES = []


def check(cond, label, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
    if not cond:
        FAILURES.append(label)


SAMPLE = """<pre>
------------------------------------------------------------------------
#     PSRJ          PSRB          RAJ         DECJ                P0          DM      S400     S1400  PSR
                                  (hms)       (dms)              (s)  (cm^-3 pc)     (mJy)     (mJy)  TYPE
------------------------------------------------------------------------
1     J0332+5434    B0329+54      03:32:59.3  +54:34:43.3   0.714520       26.76    1500.0     203.0  *
2     J0953+0755    B0950+08      09:53:09.3  +07:55:35.7   0.253065        2.97     400.0     100.0  *
3     J1745-2900    *             17:45:40.1  -29:00:29.8   3.763733     1778.00         *         *  AXP[efk+13]
4     J9999-9999    *             99:99:99.9  -99:99:99.9   1.000000        1.00         *         *  *
</pre>"""


def test_parse():
    print("\n1. catalog parsing")
    rows = pp.Catalog._parse(SAMPLE)
    check(len(rows) == 4, "all four rows parsed", f"got {len(rows)}")
    b0329 = pp.find_by_name(rows, "B0329+54")
    check(b0329 is not None and b0329["name"] == "J0332+5434",
          "B-name lookup finds the J-name row")
    check(abs(b0329["ra_deg"] - 53.2471) < 0.01, "RA hours->degrees",
          f"{b0329['ra_deg']:.4f}")
    check(abs(b0329["dec_deg"] - 54.5787) < 0.01, "Dec sexagesimal->degrees",
          f"{b0329['dec_deg']:.4f}")
    check(b0329["raj"] == 33259.3 and abs(b0329["decj"] - 543443.3) < 0.01,
          "SIGPROC packed coordinates", f"{b0329['raj']}, {b0329['decj']}")
    check(b0329["p0_s"] == 0.71452 and b0329["dm"] == 26.76, "P0 and DM")
    check(b0329["s400"] == 1500.0 and b0329["s1400"] == 203.0, "both flux columns")
    mag = pp.find_by_name(rows, "J1745-2900")
    check(pp.is_magnetar(mag), "magnetar detected from TYPE")
    check(mag["type"] == "AXP", "bracketed reference stripped from TYPE",
          repr(mag["type"]))
    check(mag["s400"] is None and mag["s1400"] is None,
          "missing flux parses as None, not 0")
    neg = pp.find_by_name(rows, "J9999-9999")
    check(neg["dec_deg"] < 0 and neg["decj"] < 0, "negative declination sign kept")


def test_coordinates():
    print("\n2. coordinates")
    ts = 1754300000.0                     # fixed instant, reproducible
    # circumpolar / never-rises from Haswell (lat 38.4): |dec| > 51.6
    check(pp.hours_above_mask(0.0, 85.0, LAT, LON, ts, 20.0) == 24.0,
          "circumpolar source never sets")
    check(pp.hours_above_mask(0.0, -85.0, LAT, LON, ts, 20.0) == 0.0,
          "southern source never rises")
    # a source at the observer's zenith right now must read alt ~90
    lst = (pp._gmst_deg(ts) + LON) % 360.0
    alt, _ = pp.altaz(lst, LAT, LAT, LON, ts)
    check(abs(alt - 90.0) < 0.5, "zenith source reads alt~90", f"{alt:.2f}")
    # astropy agreement (only if astropy is importable)
    try:
        import astropy  # noqa: F401
        a, z = pp.altaz_batch([53.2475], [54.5787], LAT, LON, ts, AMSL)
        fa, fz = pp.altaz(53.2475, 54.5787, LAT, LON, ts)
        check(abs(a[0] - fa) < 0.5 and abs(z[0] - fz) < 0.5,
              "astropy path agrees with fallback to <0.5 deg",
              f"alt {a[0]:.2f} vs {fa:.2f}")
    except ImportError:
        print("  SKIP  astropy comparison (astropy not installed)")


def test_planning():
    print("\n3. planning")
    rows = pp.Catalog._parse(SAMPLE)
    ts = 1754300000.0
    vis = pp.visible_now(rows, LAT, LON, mask_deg=0.0, unix_ts=ts,
                         center_hz=1.42e9, height_m=AMSL)
    check(all(v["alt_deg"] >= 0.0 for v in vis), "nothing below the mask returned")
    check(all("hours_left" in v and "az_deg" in v for v in vis),
          "rows annotated with az and time remaining")
    # flux follows the tuned band
    b = pp.find_by_name(rows, "B0329+54")
    f14, l14 = pp.flux_for_freq(b, 1.42e9)
    f04, l04 = pp.flux_for_freq(b, 408e6)
    check((f14, l14) == (203.0, "S1400"), "L-band picks S1400", f"{f14} {l14}")
    check((f04, l04) == (1500.0, "S400"), "UHF picks S400", f"{f04} {l04}")
    mag = pp.find_by_name(rows, "J1745-2900")
    fm, lm = pp.flux_for_freq(mag, 1.42e9)
    check(fm is None and lm == "—", "no-flux source reports no flux, not zero")
    # a flux floor must not hide magnetars
    kept = pp.visible_now(rows, LAT, LON, mask_deg=-90.0, unix_ts=ts,
                          min_flux_mjy=1e6, include_magnetars=True)
    check(any(r["magnetar"] for r in kept),
          "magnetar survives a flux floor it cannot satisfy")
    dropped = pp.visible_now(rows, LAT, LON, mask_deg=-90.0, unix_ts=ts,
                             include_magnetars=False)
    check(not any(r["magnetar"] for r in dropped),
          "magnetars excluded when the toggle is off")
    # duration warning
    circum = {"ra_deg": 0.0, "dec_deg": 85.0}
    sets, left = pp.sets_before(circum, LAT, LON, 20.0, 3600.0, ts)
    check(not sets and left == 24.0, "circumpolar source passes a 1 h recording")
    low = {"ra_deg": 0.0, "dec_deg": -85.0}
    sets, left = pp.sets_before(low, LAT, LON, 20.0, 3600.0, ts)
    check(sets and left == 0.0, "below-mask source fails a 1 h recording")


def test_next_window():
    print("\n3b. next observing window")
    ts = 1754300000.0
    # B0329+54 from Haswell: circumpolar (dec +54.6 > 90-38.4) yet it dips
    # below a 20 deg mask each day — the case that motivated the column.
    ra, dec = 53.2475, 54.5787
    lo = min(pp.altaz(ra, dec, LAT, LON, ts + i * 600)[0] for i in range(144))
    hi = max(pp.altaz(ra, dec, LAT, LON, ts + i * 600)[0] for i in range(144))
    check(lo > 0.0, "B0329+54 never sets below the horizon", f"min alt {lo:.1f}")
    check(lo < 20.0 < hi, "but does cross a 20 deg mask each day",
          f"{lo:.1f}..{hi:.1f}")
    rise, span = pp.next_window(ra, dec, LAT, LON, ts, 20.0)
    check(rise is not None and 0.0 <= rise <= 24.0,
          "next window found within a day", f"rise in {rise:.2f} h")
    check(span > 1.0, "window has a usable length", f"{span:.1f} h")
    # a source that never clears the mask reports no window
    rise2, span2 = pp.next_window(0.0, -85.0, LAT, LON, ts, 20.0)
    check(rise2 is None and span2 == 0.0, "never-visible source has no window")
    # visible_now(include_below=True) annotates both kinds
    rows = pp.Catalog._parse(SAMPLE)
    allr = pp.visible_now(rows, LAT, LON, mask_deg=20.0, unix_ts=ts,
                          include_below=True)
    check(len(allr) == len(rows), "include_below returns every source",
          f"{len(allr)}/{len(rows)}")
    check(all(("rise_in_h" in r and "window_h" in r) for r in allr),
          "every row annotated with rise/window")
    ups = [r for r in allr if not r["below_mask"]]
    check(all(r["window_h"] == r["hours_left"] for r in ups),
          "up-now rows report their remaining time as the window")


def test_cache():
    print("\n4. cache")
    with tempfile.TemporaryDirectory() as d:
        c = pp.Catalog(cache_dir=d)
        c.rows = pp.Catalog._parse(SAMPLE)
        c._save_cache()
        check(Path(d, pp.CACHE_NAME).is_file(), "cache file written")
        c2 = pp.Catalog(cache_dir=d)
        ok, age = c2._load_cache()
        check(ok and len(c2.rows) == 4, "cache reloads all rows")
        check(age < 0.01, "fresh cache reports ~zero age")
        # offline load must succeed from cache alone
        c3 = pp.Catalog(cache_dir=d)
        check(c3.load() and c3.source == "cache",
              "load() serves from cache without network")


def test_live_fetch():
    print("\n5. live ATNF fetch (network — optional)")
    if "--offline" in sys.argv:
        print("  SKIP  (--offline)")
        return
    try:
        with tempfile.TemporaryDirectory() as d:
            c = pp.Catalog(cache_dir=d)
            ok = c.load(force_refresh=True)
            check(ok and len(c.rows) > 3000,
                  "fetched a full catalog", f"{len(c.rows)} rows")
            b = pp.find_by_name(c.rows, "B0329+54")
            check(b is not None and abs(b["dm"] - 26.8) < 0.5,
                  "B0329+54 DM matches the Haswell measurement",
                  f"DM={b['dm'] if b else '?'}")
            check(sum(1 for r in c.rows if pp.is_magnetar(r)) > 10,
                  "magnetars present in the live catalog")
    except Exception as exc:
        print(f"  SKIP  network unavailable ({type(exc).__name__})")


if __name__ == "__main__":
    print("PULSAR PLANNER TESTS")
    test_parse()
    test_coordinates()
    test_planning()
    test_next_window()
    test_cache()
    test_live_fetch()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PULSAR-PLANNER TESTS PASSED")
