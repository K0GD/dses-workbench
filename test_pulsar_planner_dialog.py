#!/usr/bin/env python3
"""Headless tests for the Pulsars-in-view dialog (PulsarPlannerDialog).

The planning arithmetic is covered by test_pulsar_planner.py; this suite
covers the two things only the dialog can get wrong, both added 2026-09-10:

  1. the REFERENCE TIME control — "now" vs a planned instant, the UTC/Local
     reading of the box, the step buttons, and the fact that a planned
     instant really does reach pulsar_planner (a source's altitude has to
     change when the clock does);
  2. the TOOLTIPS — a header explanation on every column, and a per-cell
     explanation for every column of a real row, built lazily through
     _TipItem.data(ToolTipRole).

Runs offscreen with no radio, no network and no catalog download: the rows
come from test_pulsar_planner's synthetic psrcat table. Import of the app
pulls in gnuradio, so run it with the project environment's python:

    .conda/python.exe test_pulsar_planner_dialog.py
"""
import os
import sys
import time
from pathlib import Path

os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6 import QtCore, QtWidgets            # noqa: E402
from PySide6.QtCore import Qt                    # noqa: E402

import pulsar_planner as pp                      # noqa: E402
from test_pulsar_planner import SAMPLE, LAT, LON, AMSL   # noqa: E402
import dses_workbench as A                       # noqa: E402

SITE = {"lat_deg": LAT, "lon_deg": LON, "amsl": AMSL, "mask_deg": 2.0,
        "sefd_jy": 4000.0, "name": "Haswell (test)"}
CENTER_HZ = 1420.406e6
RATE_HZ = 2e6
FAILURES = []


def check(cond, label, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{'  — ' + detail if detail else ''}")
    if not cond:
        FAILURES.append(label)


def make_dialog(rows):
    dlg = A.PulsarPlannerDialog(rows, SITE, CENTER_HZ, None,
                                rate_hz=RATE_HZ, nchan=256)
    dlg._show_below.setChecked(True)      # every sample row in the table
    dlg._refresh()                         # setChecked debounces; force it
    return dlg


def row_of(dlg, name):
    """Table row index whose Pulsar cell names `name`."""
    for i in range(dlg._table.rowCount()):
        if dlg._table.item(i, 0).text().replace("  ★", "") == name:
            return i
    return -1


def test_reference_time(dlg):
    print("\n1. reference time")
    check(not dlg._plan.isChecked(), "opens on the live sky, not a plan")
    check(abs(dlg._ref_ts() - time.time()) < 5.0,
          "reference instant is now while Plan is clear")
    check("Now" in dlg._time_note.text() and "LST" in dlg._time_note.text(),
          "readout names the instant and the LST", dlg._time_note.text())

    # The box is read in the zone the combo names; switching the combo must
    # keep the same INSTANT (only its label changes).
    dlg._plan.setChecked(True)
    dlg._set_when(1789000000.0)            # 2026-09-09 17:46:40 UTC
    ts_utc = dlg._ref_ts()
    check(abs(ts_utc - 1789000000.0) < 60.0,
          "box round-trips an instant in UTC", f"{ts_utc:.0f}")
    dlg._tz.setCurrentText("Local")
    check(abs(dlg._ref_ts() - ts_utc) < 60.0,
          "switching UTC->Local keeps the same instant",
          f"{dlg._ref_ts():.0f} vs {ts_utc:.0f}")
    check(dlg._when.dateTime().toString("HH:mm")
          != time.strftime("%H:%M", time.gmtime(ts_utc))
          or time.timezone == 0,
          "...and relabels the wall clock")
    dlg._tz.setCurrentText("UTC")
    check(abs(dlg._ref_ts() - ts_utc) < 60.0, "and back again")

    # Steps move the instant and force planning mode on.
    dlg._reset_now()
    dlg._step_time(24.0)
    check(dlg._plan.isChecked(), "a step button turns planning on")
    check(23.0 < (dlg._ref_ts() - time.time()) / 3600.0 < 25.0,
          "+1 d steps one day ahead")
    dlg._step_time(-1.0)
    check(22.0 < (dlg._ref_ts() - time.time()) / 3600.0 < 24.0,
          "-1 h steps back an hour")
    dlg._reset_now()
    check(not dlg._plan.isChecked() and abs(dlg._ref_ts() - time.time()) < 5.0,
          "Now returns to the live sky")

    # Editing the box by hand is itself a request to plan.
    dlg._when.setDateTime(QtCore.QDateTime(QtCore.QDate(2026, 12, 25),
                                           QtCore.QTime(3, 0)))
    check(dlg._plan.isChecked(), "hand-editing the time turns planning on")
    dlg._reset_now()


def test_planned_table(rows):
    print("\n2. a planned instant reaches the planning code")
    # Plan for B0329+54's next meridian crossing: the table must then show
    # it at its culmination altitude — a check that holds whatever the
    # clock says when the test runs. (A fixed offset does not: alt(t) equals
    # alt(t + 12 h) twice a day, and the 2026-09-11 run landed on one.)
    dlg = make_dialog(rows)
    i = row_of(dlg, "J0332+5434")
    check(i >= 0, "B0329+54 is in the table")
    ra_b, dec_b = 53.2471, 54.5787
    now_ts = dlg._ref_ts_used
    th = pp.next_transit_h(ra_b, LON, now_ts, dec_deg=dec_b)

    dlg._plan.setChecked(True)
    dlg._set_when(now_ts + th * 3600.0)
    dlg._refresh()
    i2 = row_of(dlg, "J0332+5434")
    alt_then = float(dlg._table.item(i2, 2).text())
    culm = pp.max_alt_deg(dec_b, LAT, ra_deg=ra_b, unix_ts=now_ts)
    check(abs(alt_then - culm) < 0.5,
          "planned for its transit, the table shows B0329+54 at culmination",
          f"{alt_then:.1f}° vs {culm:.1f}° ({th:.1f} h ahead)")
    expect, _ = pp.altaz(ra_b, dec_b, LAT, LON, dlg._ref_ts_used)
    check(abs(alt_then - expect) < 1.0,
          "and matches an independent altaz() for that instant",
          f"table {alt_then:.1f}° vs {expect:.1f}°")
    check("planned" in dlg.windowTitle().lower(),
          "window title marks a planned table", dlg.windowTitle())
    check("PLANNED" in dlg._time_note.text(),
          "so does the readout beside the box")
    check(dlg._copy_context().startswith("# Pulsars in view")
          and "planned for" in dlg._copy_context()
          and "LST" in dlg._copy_context(),
          "copied tables carry a context line", dlg._copy_context())
    dlg._reset_now()
    dlg._refresh()
    check("planned" not in dlg.windowTitle().lower(),
          "title clears when back on the live sky")
    return dlg


def test_header_tips(dlg):
    print("\n3. header explanations")
    n = dlg._table.columnCount()
    check(n == len(A.PLANNER_COLUMNS),
          "table width matches PLANNER_COLUMNS", f"{n} columns")
    missing = [dlg._table.horizontalHeaderItem(c).text()
               for c in range(n)
               if len(dlg._table.horizontalHeaderItem(c).toolTip() or "") < 40]
    check(not missing, "every column header has an explanation",
          f"missing: {missing}")
    labels = [dlg._table.horizontalHeaderItem(c).text() for c in range(n)]
    check(labels == [c[0] for c in A.PLANNER_COLUMNS],
          "header labels come from the same table as the help", str(labels))


def test_cell_tips(dlg):
    print("\n4. per-cell explanations")
    i = row_of(dlg, "J0332+5434")            # bright, both flux anchors, W50
    tips = {}
    for c in range(dlg._table.columnCount()):
        it = dlg._table.item(i, c)
        tips[c] = it.data(Qt.ToolTipRole) or ""
    empty = [A.PLANNER_COLUMNS[c][0] for c, t in tips.items() if len(t) < 30]
    check(not empty, "every cell of a real row explains itself",
          f"thin: {empty}")
    check(all(len(line) <= 90 for t in tips.values() for line in t.split("\n")),
          "tooltip lines are wrapped, not one endless line")
    check("03:32:59" in tips[0] and "+54:34:43" in tips[0],
          "name cell quotes the catalog position")
    check("meridian" in tips[2] and "°" in tips[2],
          "altitude cell gives the transit")
    check(("Computed with astropy" in tips[2]) != ("closed form" in tips[2]),
          "altitude cell names the engine that computed it",
          f"engine={pp.LAST_ENGINE}")
    check("0.714520" in tips[4], "period cell quotes P0", tips[4][:60])
    check("pc cm-3" in tips[5] and "ms" in tips[5],
          "DM cell converts DM into a delay across the tuned band")
    check("S400" in tips[6] and "S1400" in tips[6],
          "flux cell names the catalog anchors it scaled from")
    check("SEFD" in tips[7] and "8-sigma" in tips[7],
          "Min rec cell lists its inputs")
    check("MHz" in tips[8] and "feeds" in tips[8],
          "Best band cell names the band and says it is feed-limited")
    check("MHz" in tips[9] and "tune anywhere" in tips[9]
          and "best real band" in tips[9],
          "Best f cell gives the free optimum and compares the real band")
    check(("mask" in tips[10]) or ("ircumpolar" in tips[10]),
          "Time left cell explains itself against the mask")
    # The two columns must agree on which is which: the free optimum can
    # never be a slower answer than the feed-limited one.
    bb = float(dlg._table.item(i, 8).text())
    bf = float(dlg._table.item(i, 9).text())
    check(100.0 <= bf <= 6000.0 and bb in (408.0, 680.5, 1299.5, 1422.0,
                                            1666.0, 2304.0),
          "Best band is a preset, Best f is any frequency",
          f"band {bb:g}  free {bf:g}")

    # Lazy and cached: the text is built on the first ToolTipRole query.
    it = dlg._table.item(i, 5)
    check(it._tip_text is not None, "tooltip cached after the first hover")
    fresh = dlg._table.item(row_of(dlg, "J0953+0755"), 5)
    check(fresh._tip_text is None,
          "a cell nobody hovered has built no text (lazy)")

    # A magnetar with no flux, no W50: the honest-silence paths.
    m = row_of(dlg, "J1745-2900")
    t_flux = dlg._table.item(m, 6).data(Qt.ToolTipRole)
    t_min = dlg._table.item(m, 7).data(Qt.ToolTipRole)
    check("no flux density" in t_flux.lower(),
          "no-flux cell says the catalog is silent, not that it is faint")
    check("not estimable" in t_min.lower(),
          "Min rec says why it cannot be estimated", t_min[:60])
    check("magnetar" in dlg._table.item(m, 0).data(Qt.ToolTipRole).lower(),
          "magnetar is called out in its name cell")

    # A source with no B name must still explain the blank.
    t_b = dlg._table.item(m, 1).data(Qt.ToolTipRole)
    check("no B1950" in t_b, "blank B-name cell explains the blank", t_b[:60])


def test_tooltip_never_raises(dlg):
    print("\n5. a broken row cannot crash a hover")
    it = A._TipItem("x", lambda: 1 / 0)
    txt = it.data(Qt.ToolTipRole)
    check("no explanation available" in txt,
          "a failing tooltip degrades to a note", txt)
    it2 = A._NumericItem("1.0", 1.0)
    check(it2.data(Qt.ToolTipRole) in (None, ""),
          "an item with no tooltip function is silent")


if __name__ == "__main__":
    print("PULSAR PLANNER DIALOG TESTS (headless)")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    rows = pp.Catalog._parse(SAMPLE)
    dlg = make_dialog(rows)
    test_reference_time(dlg)
    dlg2 = test_planned_table(rows)
    test_header_tips(dlg2)
    test_cell_tips(dlg2)
    test_tooltip_never_raises(dlg2)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PULSAR-PLANNER DIALOG TESTS PASSED")
