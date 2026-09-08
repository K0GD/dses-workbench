#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0
"""Compatibility shim -- the program is now dses_workbench.py.

The DSES Spectrum Analyzer became the DSES Radio Astronomy Workbench in 1.4.0
(2026-09-08) and its module was renamed with it. Anything that still launches
this file (an old shortcut, a script, a habit) gets the real program. It also
ships in the release bundle on purpose: an in-place update from 1.3.x
overwrites the old 9,000-line application that used to live at this path with
this shim, so a stale copy can't be started by mistake.
"""
import runpy
import sys
from pathlib import Path

_target = Path(__file__).resolve().with_name("dses_workbench.py")
if not _target.is_file():
    sys.exit(f"dses_spectrum_analyzer.py: {_target.name} not found next to this "
             "shim -- the install is incomplete.")
print("dses_spectrum_analyzer.py is now dses_workbench.py -- launching it.",
      file=sys.stderr)
sys.argv[0] = str(_target)
runpy.run_path(str(_target), run_name="__main__")
