#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: DSES Spectrum Analyzer
# Description: Spectrum analyzer for the Ettus USRP B210 and other SDRs,
# designed for pulsar RFI investigation.
# GNU Radio version: 3.10.12.0
#
# Originally generated from dses_spectrum_analyzer.grc (the .grc was never
# renamed) and then hand-polished. Migrated off gnuradio.qtgui (PyQt5) to a
# native PySide6 + PyQtGraph display so the whole app runs on one Qt
# binding (Qt6), then extended past B210-only to a multi-radio app via
# SoapySDR.

import os
import sys
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"

# Quiet known-benign chatter from underlying native libraries before any of
# them get imported. See the README; users can override any of these from
# the shell because we use setdefault rather than overwriting.
os.environ.setdefault("LIBUSB_DEBUG", "0")
os.environ.setdefault("LIBUSB_LOG_LEVEL", "0")
os.environ.setdefault("UHD_LOG_CONSOLE_LEVEL", "warning")
os.environ.setdefault("SOAPY_SDR_LOG_LEVEL", "WARNING")

# --- Windows DLL setup so SoapySDR device modules load ---
# Must run BEFORE any gnuradio.soapy / SoapySDR import. SoapySDR's support
# modules (rtlsdr, hackrf, airspy, bladerf, lime, plutosdr, audio, …) live in
# <prefix>\Library\lib\SoapySDR\modules0.8 and depend on vendor DLLs in
# <prefix>\Library\bin. When the app is launched via python.exe rather than an
# activated conda shell, that directory isn't on the DLL search path and every
# module fails with "LoadLibrary() failed: The specified module could not be
# found". The SDRplay module additionally needs the SDRplay API directory.
if os.name == "nt":
    _lib_bin = os.path.join(sys.prefix, "Library", "bin")
    _dll_dirs = [d for d in (_lib_bin, r"C:\Program Files\SDRplay\API\x64")
                 if os.path.isdir(d)]
    for _d in _dll_dirs:
        try:
            os.add_dll_directory(_d)
        except (AttributeError, OSError):
            pass
    if _dll_dirs:
        os.environ["PATH"] = os.pathsep.join(_dll_dirs) + os.pathsep + os.environ.get("PATH", "")
    # Windows searches System32 before PATH, and some machines have an older
    # C:\Windows\System32\libusb-1.0.dll (installed by Zadig / other SDR tools)
    # that lacks symbols the rtlsdr/hackrf/airspy/bladerf modules need — they
    # then fail with "The specified procedure could not be found". Pre-load
    # Radioconda's own libusb-1.0.dll by full path so it's already resident and
    # wins the base-name match for every module loaded afterward.
    _libusb = os.path.join(_lib_bin, "libusb-1.0.dll")
    if os.path.isfile(_libusb):
        try:
            import ctypes
            ctypes.CDLL(_libusb)
        except OSError:
            pass

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QObject, Signal, Slot, QTimer
import pyqtgraph as pg
pg.setConfigOption('imageAxisOrder', 'row-major')
pg.setConfigOption('background', 'k')
pg.setConfigOption('foreground', 'w')

# Scrollbars: keep the tidy "as needed" policy everywhere. On macOS the native
# scrollbar is a translucent overlay that fades out after a scroll gesture and
# can't be grabbed (and "always on" only keeps the empty track visible, not the
# thumb). Applying a stylesheet to the scrollbar forces Qt's non-native
# rendering — a solid, persistent, grabbable bar that appears whenever content
# overflows. Empty stylesheet on other platforms keeps their native look.
_VBAR_POLICY = Qt.ScrollBarAsNeeded
_SCROLLBAR_QSS = ("""
QScrollBar:vertical { width: 14px; background: palette(mid); margin: 0px; }
QScrollBar::handle:vertical { background: palette(dark); min-height: 28px;
    border-radius: 6px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent; }
""" if sys.platform == "darwin" else "")

import numpy as np
from scipy.signal import windows as scipy_windows

from gnuradio import blocks
from gnuradio import eng_notation
from gnuradio import gr
from gnuradio import uhd

# Shared, OS-neutral SIGPROC filterbank core (same module the offline
# iq_to_fil converter and PulsarLab's engine use) — provides the live .fil
# recording sink. Lives next to this script.
import sigproc_fil

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
import configparser
import re
import signal
import threading
import time


# === App metadata ===
APP_NAME        = "DSES Spectrum Analyzer"
APP_VERSION     = "1.1.1"
APP_AUTHOR      = "Richard M Hambly (K0GD)"
APP_AUTHOR_EMAIL = "rick@cnssys.com"
APP_COPYRIGHT   = "Copyright © 2026 Richard M Hambly (K0GD)"
APP_LICENSE     = "GPL-3.0-or-later"
APP_DESCRIPTION = ("Spectrum analyzer for the Ettus USRP B210 and other SDRs, "
                   "designed for pulsar RFI investigation.")
# Standalone install/upgrade guide PDF — lives next to the release zips on the
# distribution server. The update dialog points users here *before* the zip.
GUIDE_PDF_BASENAME = "DSES_RFI_Spectrum_Analyzer_Installation.pdf"


# === Window function table (drop-in for gnuradio.fft.window) ===
WINDOWS = {
    "rectangular":     lambda n: np.ones(n, dtype=np.float64),
    "hamming":         scipy_windows.hamming,
    "hann":            scipy_windows.hann,
    "blackman":        scipy_windows.blackman,
    "blackman-harris": scipy_windows.blackmanharris,
    "flat-top":        scipy_windows.flattop,
}
FFT_SIZES = [256, 512, 1024, 2048, 4096, 8192]


def _pretty_rate(hz: float) -> str:
    """Format a sample rate in Hz as a short human-readable string for the
    sample-rate combo. 1_000_000 -> '1 MHz', 2_048_000 -> '2.048 MHz',
    250_000 -> '250 kHz'."""
    mhz = hz / 1e6
    if mhz >= 1:
        if abs(mhz - round(mhz)) < 1e-6:
            return f"{int(round(mhz))} MHz"
        return f"{mhz:g} MHz"
    return f"{hz / 1e3:g} kHz"


# === User-editable settings (INI-backed, persisted across runs) ===

def _default_recording_dir():
    return str(Path.home() / "Documents" / "DSES_SA_Recordings")


DEFAULTS = {
    'tuning': {
        'preset_hz':       408e6,
        'coarse_hz':       0.0,
        'fine_hz':         0.0,
        'manual_hz':       100e6,
    },
    'rx': {
        'gain_db':         40.0,
        'samp_rate_hz':    20e6,
        # Saved (driver, serial) identifies the radio to open at startup.
        # Driver: 'uhd_b200' for B200/B210, or a Soapy driver name
        # ('sdrplay', 'rtlsdr', 'hackrf', 'airspy', 'bladerf', …).
        # Serial: 'auto' picks the first found (silent if there's only one).
        # Both are updated by the device-picker dialog when the user
        # chooses a different radio.
        'device_driver':   'uhd_b200',
        'device_serial':   'auto',
        # RF input/antenna port. Blank = use the radio's default. Only
        # meaningful on radios with more than one port (B210 TX/RX vs RX2,
        # RSPduo tuner 1 vs 2, RSPdx antenna A/B/C). Saved when the user
        # picks a port from the sidebar's Antenna combo.
        'antenna':         '',
    },
    'recording': {
        # Set at runtime from _default_recording_dir() if blank.
        'directory':       '',
        # Recording format: 'iq' = raw I/Q to SigMF (the original mode, kept);
        # 'fil' = live-channelized SIGPROC filterbank (.fil), written straight
        # to disk so the giant raw I/Q is never stored.
        'format':          'iq',
        # .fil mode geometry: polyphase/FFT channel count and the number of
        # power frames integrated per output sample (tsamp = nchans*integrate/
        # samp_rate). Defaults match the validated lab L-band geometry.
        'fil_nchans':      2048,
        'fil_integrate':   1,
    },
    'spectrum': {
        'fft_size':        1024,
        'window':          'blackman-harris',
        'normalize_window': False,
        'avg_alpha':       1.0,
        'max_hold':        False,
        'min_hold':        False,
        'y_min':           -140.0,
        'y_max':           10.0,
        'linear_scale':    False,
        'grid':            True,
        'axis_labels':     True,
        'dark_background': True,
        # Trace styling is stored per-background so the user can dial it in
        # independently for each — e.g. bright sky-blue on black vs. navy on
        # white. The active set follows `dark_background`.
        'trace_color_dark':  '#00bfff',  # deepskyblue
        'trace_width_dark':  1,
        'trace_alpha_dark':  1.0,
        'trace_label_dark':  'Data 0',
        'trace_color_light': '#003f7f',  # dark navy, legible on white
        'trace_width_light': 1,
        'trace_alpha_light': 1.0,
        'trace_label_light': 'Data 0',
    },
    'waterfall': {
        'intensity_min':   -140.0,
        'intensity_max':   10.0,
        # Per-background colormap (active follows `dark_background`).
        'colormap_dark':   'viridis',
        'colormap_light':  'inferno',
        'axis_labels':     True,
        'grid':            False,
        'dark_background': True,
        'rows':            256,
    },
    'ui': {
        'control_panels_visible': True,
    },
    'window': {
        # Main-window position/size as plain integers (human-readable and
        # corruption-proof, unlike an opaque saveGeometry() blob). width/height
        # of 0 means "not saved yet" → open at the default size.
        'x':      0,
        'y':      0,
        'width':  0,
        'height': 0,
    },
    'updates': {
        # Master switch — set to false to disable the auto-check entirely.
        'auto_check':           True,
        # URL of the manifest.json describing the latest release. See
        # Installing.md "Release workflow" for the expected JSON format.
        'manifest_url':         'https://gpstime.com/sw_distribution/b210_sa/manifest.json',
        # ISO-8601 timestamp of the last successful check (set by the app).
        # Used to debounce repeated launches.
        'last_check_iso':       '',
        # Don't open the notification dialog more often than this many
        # hours regardless of how many times the app is relaunched.
        'check_interval_hours': 24,
        # If the user clicks "Skip this version" on the notification, the
        # version they skipped is stored here so we don't nag them again
        # until a newer one appears.
        'dismissed_version':    '',
    },
}


def _settings_path():
    """Cross-platform config location. Matches launcher.ps1's
    %APPDATA%\\DSES_Analyzer on Windows; main() sets QApplication app name
    to 'DSES_Analyzer' with no org, so AppDataLocation resolves to:
        Windows: %APPDATA%/DSES_Analyzer/
        macOS:   ~/Library/Application Support/DSES_Analyzer/
        Linux:   ~/.local/share/DSES_Analyzer/
    """
    base = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.AppDataLocation)
    if not base:
        base = str(Path.home() / ".config" / "DSES_Analyzer")
    cfg_dir = Path(base)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "settings.ini"


class Settings:
    """INI-backed settings store. Missing keys fall back to DEFAULTS, so the
    file is always usable even if the user deletes individual lines. Save
    rewrites the whole file with a header comment explaining what it is."""

    def __init__(self, path=None):
        self.path = Path(path) if path else _settings_path()
        self._cp = configparser.ConfigParser()
        # Preserve case of keys (configparser lowercases by default).
        self._cp.optionxform = lambda optionstr: optionstr
        if self.path.exists():
            try:
                # utf-8-sig transparently strips a UTF-8 BOM if present —
                # Windows editors (Notepad, PowerShell Set-Content -Encoding
                # UTF8) often add one, and configparser would otherwise die
                # with "File contains no section headers" on the BOM'd line 1.
                self._cp.read(self.path, encoding="utf-8-sig")
            except (configparser.Error, OSError) as exc:
                print(f"Settings: failed to read {self.path}: {exc}", file=sys.stderr)
        self._migrate_legacy_keys()
        self._fill_missing_with_defaults()
        # Materialise defaults for the recording directory on first run.
        if not self._cp.get('recording', 'directory'):
            self._cp.set('recording', 'directory', _default_recording_dir())
        # Write the file back so the user has a complete template to edit.
        try:
            self.save()
        except OSError as exc:
            print(f"Settings: failed to write {self.path}: {exc}", file=sys.stderr)

    def _migrate_legacy_keys(self):
        """Rename keys that changed meaning across versions. Runs before
        _fill_missing_with_defaults so the user's existing value seeds the
        new key instead of being replaced by the built-in default."""
        # v1.0.0 → v1.1.0: trace styling and colormap became per-background.
        # The pre-1.1.0 single value becomes the dark-background value.
        legacy = [
            ('spectrum',  'trace_color',  'trace_color_dark'),
            ('spectrum',  'trace_width',  'trace_width_dark'),
            ('spectrum',  'trace_alpha',  'trace_alpha_dark'),
            ('spectrum',  'trace_label',  'trace_label_dark'),
            ('waterfall', 'colormap',     'colormap_dark'),
        ]
        for section, old, new in legacy:
            if (self._cp.has_section(section)
                    and self._cp.has_option(section, old)
                    and not self._cp.has_option(section, new)):
                self._cp.set(section, new, self._cp.get(section, old))
                self._cp.remove_option(section, old)
        # Obsolete: window geometry was briefly stored as a base64
        # saveGeometry() blob; it's now plain x/y/width/height. Drop the dead
        # key so it doesn't linger in the file.
        if self._cp.has_section('window') and self._cp.has_option('window', 'geometry_b64'):
            self._cp.remove_option('window', 'geometry_b64')

    def _fill_missing_with_defaults(self):
        for section, kvs in DEFAULTS.items():
            if not self._cp.has_section(section):
                self._cp.add_section(section)
            for k, v in kvs.items():
                if not self._cp.has_option(section, k):
                    self._cp.set(section, k, self._stringify(v))

    @staticmethod
    def _stringify(v):
        if isinstance(v, bool):
            return 'true' if v else 'false'
        return str(v)

    def get_str(self, section, key):
        return self._cp.get(section, key)

    def get_int(self, section, key):
        return int(float(self._cp.get(section, key)))

    def get_float(self, section, key):
        return float(self._cp.get(section, key))

    def get_bool(self, section, key):
        return self._cp.get(section, key).strip().lower() in ('true', 'yes', '1', 'on')

    def set(self, section, key, value):
        if not self._cp.has_section(section):
            self._cp.add_section(section)
        self._cp.set(section, key, self._stringify(value))

    def save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(f"# {APP_NAME} v{APP_VERSION} settings\n")
            f.write(f"# File: {self.path}\n")
            f.write("#\n")
            f.write("# This file is plain text and may be edited with any editor while the\n")
            f.write("# program is closed. Comments begin with '#' or ';'. Missing keys are\n")
            f.write("# filled in from built-in defaults on next launch. To wipe everything\n")
            f.write("# back to defaults, use 'Restore Defaults' in Help → About.\n\n")
            self._cp.write(f)

    def reset_to_defaults(self):
        self._cp = configparser.ConfigParser()
        self._cp.optionxform = lambda optionstr: optionstr
        self._fill_missing_with_defaults()
        self._cp.set('recording', 'directory', _default_recording_dir())
        self.save()


CHUNK_SIZE = 8192  # Must be >= max FFT size in FFT_SIZES below.


class SampleBufferSink(gr.sync_block):
    """Stores the most-recent CHUNK_SIZE-sample complex-baseband vector.
    Fed by stream_to_vector + keep_one_in_n upstream so this Python block
    only sees a handful of vectors per second — pure-Python sync_blocks
    can't keep up with 20 MS/s sample-by-sample input."""

    def __init__(self, chunk_size=CHUNK_SIZE):
        gr.sync_block.__init__(
            self,
            name="sample_buffer_sink",
            in_sig=[(np.complex64, chunk_size)],
            out_sig=None,
        )
        self._lock = threading.Lock()
        self._chunk_size = int(chunk_size)
        self._buf = np.zeros(self._chunk_size, dtype=np.complex64)
        self._filled = False

    @property
    def chunk_size(self):
        return self._chunk_size

    def set_capacity(self, _n):
        # Capacity is fixed at chunk_size (set at flowgraph construction).
        # Kept as a no-op so SpectrumProcessor.set_fft_size still calls it
        # without needing flowgraph relock.
        return

    def work(self, input_items, output_items):
        chunks = input_items[0]
        n = len(chunks)
        if n > 0:
            latest = chunks[-1]
            with self._lock:
                self._buf[:] = latest
                self._filled = True
        return n

    def latest(self, n):
        """Return the most recent n samples (chronological order), or None
        if no chunk has arrived yet or n exceeds chunk_size."""
        n = int(n)
        with self._lock:
            if not self._filled or n > self._chunk_size or n <= 0:
                return None
            return self._buf[-n:].copy()


class SpectrumProcessor(QObject):
    """Pulls samples from a SampleBufferSink on a QTimer, computes a windowed
    FFT, applies exponential averaging plus optional max/min hold, and emits
    `frame_ready(avg_db, max_db, min_db)` so plot widgets can update."""

    frame_ready = Signal(object, object, object)  # avg_db, max_db|None, min_db|None

    def __init__(self, sink, fft_size=1024, window_name="blackman-harris",
                 update_hz=10.0, normalize=False, parent=None):
        super().__init__(parent)
        self._sink = sink
        self._fft_size = int(fft_size)
        self._window_name = window_name
        self._window = WINDOWS[window_name](self._fft_size).astype(np.float64)
        self._normalize = bool(normalize)
        self._avg_alpha = 1.0
        self._max_on = False
        self._min_on = False
        self._avg_db = None
        self._max_db = None
        self._min_db = None
        self._sink.set_capacity(max(8192, self._fft_size * 2))

        self._timer = QTimer(self)
        self._timer.setInterval(max(20, int(1000.0 / update_hz)))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @Slot(int)
    def set_fft_size(self, n):
        self._fft_size = int(n)
        self._window = WINDOWS[self._window_name](self._fft_size).astype(np.float64)
        self._sink.set_capacity(max(8192, self._fft_size * 2))
        self._avg_db = self._max_db = self._min_db = None

    @Slot(str)
    def set_window(self, name):
        if name not in WINDOWS:
            return
        self._window_name = name
        self._window = WINDOWS[name](self._fft_size).astype(np.float64)

    @Slot(float)
    def set_average_alpha(self, alpha):
        """alpha in (0, 1]. 1.0 = no averaging, smaller = more smoothing."""
        self._avg_alpha = float(np.clip(alpha, 1e-3, 1.0))

    @Slot(bool)
    def set_max_hold(self, on):
        self._max_on = bool(on)
        if not on:
            self._max_db = None

    @Slot(bool)
    def set_min_hold(self, on):
        self._min_on = bool(on)
        if not on:
            self._min_db = None

    @Slot()
    def reset_max_hold(self):
        self._max_db = None

    @Slot()
    def reset_min_hold(self):
        self._min_db = None

    @Slot(bool)
    def set_window_normalized(self, on):
        self._normalize = bool(on)

    def set_update_hz(self, hz):
        self._timer.setInterval(max(20, int(1000.0 / float(hz))))

    def _tick(self):
        n = self._fft_size
        samples = self._sink.latest(n)
        if samples is None:
            return
        windowed = samples * self._window
        spec = np.fft.fftshift(np.fft.fft(windowed))
        if self._normalize:
            wsum = np.sum(self._window) or 1.0
            power = (np.abs(spec) ** 2) / (wsum * wsum)
        else:
            wpow = np.sum(self._window ** 2) or 1.0
            power = (np.abs(spec) ** 2) / (n * wpow)
        db = 10.0 * np.log10(power + 1e-20)

        if self._avg_db is None or len(self._avg_db) != n:
            self._avg_db = db.copy()
        else:
            a = self._avg_alpha
            self._avg_db = a * db + (1.0 - a) * self._avg_db

        if self._max_on:
            if self._max_db is None or len(self._max_db) != n:
                self._max_db = self._avg_db.copy()
            else:
                np.maximum(self._max_db, self._avg_db, out=self._max_db)
        if self._min_on:
            if self._min_db is None or len(self._min_db) != n:
                self._min_db = self._avg_db.copy()
            else:
                np.minimum(self._min_db, self._avg_db, out=self._min_db)

        self.frame_ready.emit(
            self._avg_db,
            self._max_db if self._max_on else None,
            self._min_db if self._min_on else None,
        )


def _make_pen(color, width, alpha):
    c = QtGui.QColor(color)
    c.setAlphaF(float(alpha))
    return pg.mkPen(c, width=width)


def _apply_plot_theme(plot, title, dark):
    """Switch a pg.PlotWidget between dark (black bg / white axes) and light
    (white bg / black axes). pg.setConfigOption('foreground', ...) only
    affects newly-created items, so we update axes and title per-plot."""
    bg = 'k' if dark else 'w'
    fg = 'w' if dark else 'k'
    plot.setBackground(bg)
    for name in ('left', 'bottom', 'right', 'top'):
        ax = plot.getAxis(name)
        if ax is None:
            continue
        ax.setPen(fg)
        ax.setTextPen(fg)
    plot.setTitle(title, color=fg)


class FftPlotWidget(QtWidgets.QWidget):
    """Spectrum (FFT) plot with a collapsible right-side control panel
    reproducing the qtgui freq_sink controls: FFT size, window, averaging,
    max/min hold, Y-axis (min/max/autoscale), grid, axis labels, trace
    color / width / alpha / label."""

    request_fft_size = Signal(int)
    request_window = Signal(str)
    request_average = Signal(float)
    request_max_hold = Signal(bool)
    request_min_hold = Signal(bool)
    request_reset_max = Signal()
    request_reset_min = Signal()
    request_window_normalized = Signal(bool)
    # Fires on every user-driven control change; args: (settings_key, value).
    # The main window listens once and persists to the INI.
    control_changed = Signal(str, object)

    def __init__(self, center_freq, samp_rate, parent=None):
        super().__init__(parent)
        self._center_freq = float(center_freq)
        self._samp_rate = float(samp_rate)
        self._y_min = -140.0
        self._y_max = 10.0
        self._linear = False      # False = dB (log) scale, True = linear amplitude
        self._labels_on = True    # axis-label visibility (mirrors the checkbox)
        self._dark_bg = True
        # Per-background trace styling. The Trace controls in the panel show
        # whichever set matches `_dark_bg`. Edits write to the active set;
        # toggling the background swaps them. apply_settings() will overwrite
        # both from the INI on startup.
        self._trace_dark = {
            'color': QtGui.QColor("deepskyblue"),
            'width': 1, 'alpha': 1.0, 'label': "Data 0",
        }
        self._trace_light = {
            'color': QtGui.QColor("#003f7f"),
            'width': 1, 'alpha': 1.0, 'label': "Data 0",
        }
        # Live values mirror the active slot; used by handlers + pen building.
        self._line_color = self._trace_dark['color']
        self._line_width = self._trace_dark['width']
        self._line_alpha = self._trace_dark['alpha']
        self._line_label = self._trace_dark['label']

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._plot = pg.PlotWidget()
        self._plot.setLabel('left', 'Relative Gain', units='dB')
        self._plot.setLabel('bottom', 'Frequency', units='Hz')
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setYRange(self._y_min, self._y_max)
        _apply_plot_theme(self._plot, "Spectrum", self._dark_bg)
        self._curve = self._plot.plot(
            pen=_make_pen(self._line_color, self._line_width, self._line_alpha),
            name=self._line_label)
        self._max_curve = self._plot.plot(
            pen=_make_pen(QtGui.QColor(50, 220, 50), 1, 1.0), name="Max hold")
        self._min_curve = self._plot.plot(
            pen=_make_pen(QtGui.QColor(220, 50, 50), 1, 1.0), name="Min hold")
        self._max_curve.hide()
        self._min_curve.hide()
        layout.addWidget(self._plot, 1)

        self._toggle_btn = QtWidgets.QToolButton()
        self._toggle_btn.setText("▸")
        self._toggle_btn.setToolTip("Hide/show controls")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(True)
        self._toggle_btn.toggled.connect(self._on_toggle_panel)
        toggle_col = QtWidgets.QVBoxLayout()
        toggle_col.setContentsMargins(0, 0, 0, 0)
        toggle_col.addWidget(self._toggle_btn)
        toggle_col.addStretch(1)
        toggle_wrap = QtWidgets.QWidget()
        toggle_wrap.setLayout(toggle_col)
        layout.addWidget(toggle_wrap)

        self._panel = self._build_panel()
        # Scroll the controls so a tall stack never forces the whole window
        # taller than the screen — it scrolls within the panel instead.
        self._panel_scroll = QtWidgets.QScrollArea()
        self._panel_scroll.setWidget(self._panel)
        self._panel_scroll.setWidgetResizable(True)
        self._panel_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._panel_scroll.setVerticalScrollBarPolicy(_VBAR_POLICY)
        self._panel_scroll.verticalScrollBar().setStyleSheet(_SCROLLBAR_QSS)
        self._panel_scroll.setFixedWidth(248)   # 230 panel + room for scrollbar
        self._panel_scroll.setMinimumHeight(80)  # let the window shrink past it
        layout.addWidget(self._panel_scroll)

    def _build_panel(self):
        panel = QtWidgets.QGroupBox("Spectrum Controls")
        # Fixed width (matched on the waterfall panel) so the spectrum and
        # waterfall plot regions stay equal-width regardless of content.
        panel.setFixedWidth(230)
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        # FFT group
        fft_group = QtWidgets.QGroupBox("FFT")
        f = QtWidgets.QFormLayout(fft_group)
        f.setContentsMargins(4, 4, 4, 4)
        self._fft_size_combo = QtWidgets.QComboBox()
        for n in FFT_SIZES:
            self._fft_size_combo.addItem(str(n), n)
        self._fft_size_combo.setCurrentText("1024")
        self._fft_size_combo.currentIndexChanged.connect(
            lambda _i: self.request_fft_size.emit(self._fft_size_combo.currentData()))
        self._fft_size_combo.currentIndexChanged.connect(
            lambda _i: self.control_changed.emit('fft_size', self._fft_size_combo.currentData()))
        f.addRow("Size:", self._fft_size_combo)

        self._window_combo = QtWidgets.QComboBox()
        for name in WINDOWS.keys():
            self._window_combo.addItem(name)
        self._window_combo.setCurrentText("blackman-harris")
        self._window_combo.currentTextChanged.connect(self.request_window.emit)
        self._window_combo.currentTextChanged.connect(
            lambda s: self.control_changed.emit('window', s))
        f.addRow("Window:", self._window_combo)

        self._norm_check = QtWidgets.QCheckBox("Normalize window")
        self._norm_check.toggled.connect(self.request_window_normalized.emit)
        self._norm_check.toggled.connect(
            lambda on: self.control_changed.emit('normalize_window', on))
        f.addRow(self._norm_check)

        self._avg_slider = QtWidgets.QSlider(Qt.Horizontal)
        self._avg_slider.setRange(1, 1000)
        self._avg_slider.setValue(1000)
        self._avg_slider.valueChanged.connect(lambda v: self.request_average.emit(v / 1000.0))
        self._avg_slider.valueChanged.connect(
            lambda v: self.control_changed.emit('avg_alpha', v / 1000.0))
        self._avg_value_lbl = QtWidgets.QLabel("1.000")
        self._avg_slider.valueChanged.connect(lambda v: self._avg_value_lbl.setText(f"{v/1000.0:.3f}"))
        avg_row = QtWidgets.QHBoxLayout()
        avg_row.addWidget(self._avg_slider, 1)
        avg_row.addWidget(self._avg_value_lbl)
        f.addRow("Avg α:", avg_row)
        v.addWidget(fft_group)

        # Hold group
        hold_group = QtWidgets.QGroupBox("Hold")
        g = QtWidgets.QGridLayout(hold_group)
        g.setContentsMargins(4, 4, 4, 4)
        self._max_check = QtWidgets.QCheckBox("Max hold")
        self._max_check.toggled.connect(self._on_max_toggled)
        self._max_check.toggled.connect(
            lambda on: self.control_changed.emit('max_hold', on))
        max_reset = QtWidgets.QPushButton("Reset")
        max_reset.clicked.connect(self.request_reset_max.emit)
        g.addWidget(self._max_check, 0, 0)
        g.addWidget(max_reset, 0, 1)
        self._min_check = QtWidgets.QCheckBox("Min hold")
        self._min_check.toggled.connect(self._on_min_toggled)
        self._min_check.toggled.connect(
            lambda on: self.control_changed.emit('min_hold', on))
        min_reset = QtWidgets.QPushButton("Reset")
        min_reset.clicked.connect(self.request_reset_min.emit)
        g.addWidget(self._min_check, 1, 0)
        g.addWidget(min_reset, 1, 1)
        v.addWidget(hold_group)

        # Y-axis group
        y_group = QtWidgets.QGroupBox("Y-Axis")
        yf = QtWidgets.QFormLayout(y_group)
        yf.setContentsMargins(4, 4, 4, 4)
        self._ymin_spin = QtWidgets.QDoubleSpinBox()
        self._ymin_spin.setRange(-300, 100); self._ymin_spin.setValue(self._y_min)
        self._ymin_spin.valueChanged.connect(self._on_yrange_changed)
        self._ymin_spin.valueChanged.connect(
            lambda v: self.control_changed.emit('y_min', v))
        yf.addRow("Min:", self._ymin_spin)
        self._ymax_spin = QtWidgets.QDoubleSpinBox()
        self._ymax_spin.setRange(-200, 200); self._ymax_spin.setValue(self._y_max)
        self._ymax_spin.valueChanged.connect(self._on_yrange_changed)
        self._ymax_spin.valueChanged.connect(
            lambda v: self.control_changed.emit('y_max', v))
        yf.addRow("Max:", self._ymax_spin)
        autoscale_btn = QtWidgets.QPushButton("Autoscale")
        autoscale_btn.clicked.connect(lambda: self._plot.enableAutoRange(axis='y'))
        yf.addRow(autoscale_btn)
        reset_axes_btn = QtWidgets.QPushButton("Reset Axes")
        reset_axes_btn.setToolTip(
            "Restore the default Y range and full-span frequency view "
            "(undoes manual min/max edits and any mouse zoom/pan). "
            "Leaves FFT size, window, traces, and colors unchanged.")
        reset_axes_btn.clicked.connect(self.reset_axes)
        yf.addRow(reset_axes_btn)
        self._linear_check = QtWidgets.QCheckBox("Linear scale")
        self._linear_check.setToolTip(
            "Plot linear magnitude instead of dB (log). The dB Min/Max boxes "
            "don't apply in linear mode — the Y axis auto-fits. Affects the "
            "spectrum plot only; the waterfall stays in dB.")
        self._linear_check.toggled.connect(self._on_linear_scale_toggled)
        self._linear_check.toggled.connect(
            lambda on: self.control_changed.emit('linear_scale', on))
        yf.addRow(self._linear_check)
        v.addWidget(y_group)

        # Display group
        disp_group = QtWidgets.QGroupBox("Display")
        dv = QtWidgets.QVBoxLayout(disp_group)
        dv.setContentsMargins(4, 4, 4, 4)
        self._grid_check = QtWidgets.QCheckBox("Grid")
        self._grid_check.setChecked(True)
        self._grid_check.toggled.connect(lambda on: self._plot.showGrid(x=on, y=on, alpha=0.3))
        self._grid_check.toggled.connect(
            lambda on: self.control_changed.emit('grid', on))
        dv.addWidget(self._grid_check)
        self._labels_check = QtWidgets.QCheckBox("Axis labels")
        self._labels_check.setChecked(True)
        self._labels_check.toggled.connect(self._on_labels_toggled)
        self._labels_check.toggled.connect(
            lambda on: self.control_changed.emit('axis_labels', on))
        dv.addWidget(self._labels_check)
        self._dark_bg_check = QtWidgets.QCheckBox("Dark background")
        self._dark_bg_check.setChecked(self._dark_bg)
        self._dark_bg_check.toggled.connect(self._on_dark_bg_toggled)
        self._dark_bg_check.toggled.connect(
            lambda on: self.control_changed.emit('dark_background', on))
        dv.addWidget(self._dark_bg_check)
        v.addWidget(disp_group)

        # Trace group
        tr_group = QtWidgets.QGroupBox("Trace")
        tf = QtWidgets.QFormLayout(tr_group)
        tf.setContentsMargins(4, 4, 4, 4)
        self._color_btn = QtWidgets.QPushButton()
        self._color_btn.setStyleSheet(f"background-color: {self._line_color.name()};")
        self._color_btn.clicked.connect(self._on_color_clicked)
        tf.addRow("Color:", self._color_btn)
        self._width_spin = QtWidgets.QSpinBox()
        self._width_spin.setRange(1, 10); self._width_spin.setValue(self._line_width)
        self._width_spin.valueChanged.connect(self._on_width_changed)
        self._width_spin.valueChanged.connect(
            lambda v: self.control_changed.emit(self._trace_key('trace_width'), int(v)))
        tf.addRow("Width:", self._width_spin)
        self._alpha_slider = QtWidgets.QSlider(Qt.Horizontal)
        self._alpha_slider.setRange(10, 100); self._alpha_slider.setValue(int(self._line_alpha * 100))
        self._alpha_slider.valueChanged.connect(self._on_alpha_changed)
        self._alpha_slider.valueChanged.connect(
            lambda v: self.control_changed.emit(self._trace_key('trace_alpha'), v / 100.0))
        tf.addRow("Alpha:", self._alpha_slider)
        self._label_edit = QtWidgets.QLineEdit(self._line_label)
        self._label_edit.editingFinished.connect(self._on_label_changed)
        self._label_edit.editingFinished.connect(
            lambda: self.control_changed.emit(self._trace_key('trace_label'), self._label_edit.text()))
        tf.addRow("Label:", self._label_edit)
        v.addWidget(tr_group)

        v.addStretch(1)
        return panel

    @staticmethod
    def _to_linear(db):
        # The processor emits power-dB (10·log10(power)); linear amplitude is
        # 10^(dB/20). Display-only transform; the data pipeline stays in dB.
        return np.power(10.0, np.asarray(db) / 20.0)

    @Slot(object, object, object)
    def on_frame(self, avg_db, max_db, min_db):
        n = len(avg_db)
        freqs = self._center_freq + np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / self._samp_rate))
        avg = self._to_linear(avg_db) if self._linear else avg_db
        mx = (self._to_linear(max_db) if self._linear else max_db) if max_db is not None else None
        mn = (self._to_linear(min_db) if self._linear else min_db) if min_db is not None else None
        self._curve.setData(freqs, avg)
        if mx is not None:
            self._max_curve.setData(freqs, mx); self._max_curve.show()
        else:
            self._max_curve.hide()
        if mn is not None:
            self._min_curve.setData(freqs, mn); self._min_curve.show()
        else:
            self._min_curve.hide()

    def set_frequency_range(self, center_freq, bandwidth):
        self._center_freq = float(center_freq)
        self._samp_rate = float(bandwidth)
        self._plot.setXRange(center_freq - bandwidth / 2.0,
                             center_freq + bandwidth / 2.0, padding=0)

    def set_y_axis(self, y_min, y_max):
        self._y_min = float(y_min); self._y_max = float(y_max)
        self._plot.setYRange(y_min, y_max)
        for spin, val in ((self._ymin_spin, y_min), (self._ymax_spin, y_max)):
            spin.blockSignals(True); spin.setValue(val); spin.blockSignals(False)

    def reset_axes(self):
        """Snap the spectrum view back to defaults: built-in Y range plus the
        full-span frequency view for the current center/sample rate. Undoes
        manual Y min/max edits and any mouse pan/zoom, without touching FFT
        size, window, averaging, traces, or colors. The Y values are persisted
        so the reset survives a restart."""
        if self._linear:
            # Linear mode has no fixed dB range; just auto-fit Y.
            self._plot.enableAutoRange(axis='y')
        else:
            y_min = DEFAULTS['spectrum']['y_min']
            y_max = DEFAULTS['spectrum']['y_max']
            self._plot.disableAutoRange()
            self.set_y_axis(y_min, y_max)
            self.control_changed.emit('y_min', y_min)
            self.control_changed.emit('y_max', y_max)
        # Restore the full frequency span (re-derives X from center/bandwidth).
        self.set_frequency_range(self._center_freq, self._samp_rate)

    def _on_toggle_panel(self, on):
        self._panel_scroll.setVisible(on)
        self._toggle_btn.setText("▸" if on else "◂")

    def _on_yrange_changed(self, _v):
        self._plot.setYRange(self._ymin_spin.value(), self._ymax_spin.value())

    def _on_labels_toggled(self, on):
        self._labels_on = bool(on)
        self._update_y_label()
        self._plot.setLabel('bottom', 'Frequency' if on else '', units='Hz' if on else '')

    def _update_y_label(self):
        """Set the left-axis label to match the scale mode + label visibility."""
        if not self._labels_on:
            self._plot.setLabel('left', '', units='')
        elif self._linear:
            self._plot.setLabel('left', 'Magnitude (linear)', units='')
        else:
            self._plot.setLabel('left', 'Relative Gain', units='dB')

    def _on_linear_scale_toggled(self, on):
        self._linear = bool(on)
        self._update_y_label()
        # The dB Min/Max spinboxes are meaningless in linear mode; disable them
        # and let the Y axis auto-fit the linear data. Back in dB, restore the
        # saved fixed range.
        self._ymin_spin.setEnabled(not self._linear)
        self._ymax_spin.setEnabled(not self._linear)
        if self._linear:
            self._plot.enableAutoRange(axis='y')
        else:
            self._plot.setYRange(self._ymin_spin.value(), self._ymax_spin.value())

    def _on_dark_bg_toggled(self, on):
        # Save the live trace styling into the OLD slot before switching.
        self._snapshot_trace_to_slot(self._dark_bg)
        self._dark_bg = bool(on)
        _apply_plot_theme(self._plot, "Spectrum", self._dark_bg)
        # Pull the NEW slot's trace styling back into the live fields and UI.
        self._restore_trace_from_slot(self._dark_bg)

    def _theme_suffix(self):
        return "dark" if self._dark_bg else "light"

    def _trace_key(self, base):
        return f"{base}_{self._theme_suffix()}"

    def _slot_for(self, dark):
        return self._trace_dark if dark else self._trace_light

    def _snapshot_trace_to_slot(self, dark):
        slot = self._slot_for(dark)
        slot['color'] = self._line_color
        slot['width'] = self._line_width
        slot['alpha'] = self._line_alpha
        slot['label'] = self._line_label

    def _restore_trace_from_slot(self, dark):
        slot = self._slot_for(dark)
        self._line_color = slot['color']
        self._line_width = slot['width']
        self._line_alpha = slot['alpha']
        self._line_label = slot['label']
        with _SignalBlocker(self._width_spin, self._alpha_slider, self._label_edit):
            self._color_btn.setStyleSheet(f"background-color: {self._line_color.name()};")
            self._width_spin.setValue(self._line_width)
            self._alpha_slider.setValue(int(round(self._line_alpha * 100)))
            self._label_edit.setText(self._line_label)
        self._curve.setPen(_make_pen(self._line_color, self._line_width, self._line_alpha))

    def _on_max_toggled(self, on):
        self.request_max_hold.emit(on)
        if not on:
            self._max_curve.hide()

    def _on_min_toggled(self, on):
        self.request_min_hold.emit(on)
        if not on:
            self._min_curve.hide()

    def _on_color_clicked(self):
        c = QtWidgets.QColorDialog.getColor(self._line_color, self, "Trace color")
        if c.isValid():
            self._line_color = c
            # Keep the active per-bg slot in lock-step with the live value so
            # a later bg-toggle's snapshot is a no-op rather than the only
            # thing keeping the slot fresh.
            self._slot_for(self._dark_bg)['color'] = c
            self._color_btn.setStyleSheet(f"background-color: {c.name()};")
            self._curve.setPen(_make_pen(c, self._line_width, self._line_alpha))
            self.control_changed.emit(self._trace_key('trace_color'), c.name())

    def _on_width_changed(self, w):
        self._line_width = int(w)
        self._slot_for(self._dark_bg)['width'] = self._line_width
        self._curve.setPen(_make_pen(self._line_color, self._line_width, self._line_alpha))

    def _on_alpha_changed(self, v):
        self._line_alpha = v / 100.0
        self._slot_for(self._dark_bg)['alpha'] = self._line_alpha
        self._curve.setPen(_make_pen(self._line_color, self._line_width, self._line_alpha))

    def _on_label_changed(self):
        self._line_label = self._label_edit.text()
        self._slot_for(self._dark_bg)['label'] = self._line_label

    # --- programmatic setters (used to push values from Settings into the UI) ---
    # Each one blocks signals so applying a saved value doesn't re-trigger a save.
    def apply_settings(self, settings):
        """Push every value from the spectrum section of `settings` into the UI."""
        section = 'spectrum'
        # Load both per-background trace slots from disk so toggling is instant
        # and doesn't need to re-read.
        for which in ('dark', 'light'):
            slot = self._slot_for(which == 'dark')
            color = QtGui.QColor(settings.get_str(section, f'trace_color_{which}'))
            if color.isValid():
                slot['color'] = color
            slot['width'] = settings.get_int(section, f'trace_width_{which}')
            slot['alpha'] = settings.get_float(section, f'trace_alpha_{which}')
            slot['label'] = settings.get_str(section, f'trace_label_{which}')

        with _SignalBlocker(self._fft_size_combo, self._window_combo, self._norm_check,
                            self._avg_slider, self._max_check, self._min_check,
                            self._ymin_spin, self._ymax_spin, self._grid_check,
                            self._labels_check, self._dark_bg_check, self._width_spin,
                            self._alpha_slider, self._label_edit, self._linear_check):
            idx = self._fft_size_combo.findData(settings.get_int(section, 'fft_size'))
            if idx >= 0:
                self._fft_size_combo.setCurrentIndex(idx)
            self._window_combo.setCurrentText(settings.get_str(section, 'window'))
            self._norm_check.setChecked(settings.get_bool(section, 'normalize_window'))
            a = settings.get_float(section, 'avg_alpha')
            self._avg_slider.setValue(int(round(max(0.001, min(1.0, a)) * 1000)))
            self._avg_value_lbl.setText(f"{a:.3f}")
            self._max_check.setChecked(settings.get_bool(section, 'max_hold'))
            self._min_check.setChecked(settings.get_bool(section, 'min_hold'))
            self._ymin_spin.setValue(settings.get_float(section, 'y_min'))
            self._ymax_spin.setValue(settings.get_float(section, 'y_max'))
            self._grid_check.setChecked(settings.get_bool(section, 'grid'))
            self._labels_check.setChecked(settings.get_bool(section, 'axis_labels'))
            self._dark_bg_check.setChecked(settings.get_bool(section, 'dark_background'))
            self._linear_check.setChecked(settings.get_bool(section, 'linear_scale'))
            # Trace controls are filled from the active slot below via
            # _restore_trace_from_slot; nothing to set here.
        # Apply the effects that the blocked signals would normally have triggered.
        self._dark_bg = self._dark_bg_check.isChecked()
        self._labels_on = self._labels_check.isChecked()
        self._plot.setYRange(self._ymin_spin.value(), self._ymax_spin.value())
        self._plot.showGrid(x=self._grid_check.isChecked(), y=self._grid_check.isChecked(), alpha=0.3)
        self._on_labels_toggled(self._labels_check.isChecked())
        # Apply the saved scale mode (sets label, spinbox-enable, Y range).
        self._on_linear_scale_toggled(self._linear_check.isChecked())
        _apply_plot_theme(self._plot, "Spectrum", self._dark_bg)
        # Populate the Trace controls + pen from whichever slot is active.
        self._restore_trace_from_slot(self._dark_bg)

    def emit_settings_to_processor(self):
        """Re-emit request_* signals from current UI state. Used after
        apply_settings (which blocked signals) so the processor catches up."""
        self.request_fft_size.emit(self._fft_size_combo.currentData())
        self.request_window.emit(self._window_combo.currentText())
        self.request_window_normalized.emit(self._norm_check.isChecked())
        self.request_average.emit(self._avg_slider.value() / 1000.0)
        self.request_max_hold.emit(self._max_check.isChecked())
        self.request_min_hold.emit(self._min_check.isChecked())


class _SignalBlocker:
    """Context manager that blocks signals on a set of QObjects."""
    def __init__(self, *objs):
        self._objs = objs
        self._prev = []
    def __enter__(self):
        self._prev = [o.blockSignals(True) for o in self._objs]
        return self
    def __exit__(self, *_):
        for o, prev in zip(self._objs, self._prev):
            o.blockSignals(prev)


class WaterfallPlotWidget(QtWidgets.QWidget):
    """Scrolling waterfall (pg.ImageItem) with control panel: intensity
    min/max, autoscale, colormap, grid/axis toggles, row count."""

    # Fires on every user-driven control change; args: (settings_key, value).
    control_changed = Signal(str, object)

    def __init__(self, center_freq, samp_rate, rows=256, parent=None):
        super().__init__(parent)
        self._center_freq = float(center_freq)
        self._samp_rate = float(samp_rate)
        self._rows = int(rows)
        self._intensity_min = -140.0
        self._intensity_max = 10.0
        self._dark_bg = True
        # Per-background colormap. The Colormap combo shows the one matching
        # `_dark_bg`; edits update the matching slot; toggling the background
        # swaps them. apply_settings() overwrites both from the INI.
        self._cmap_dark = "viridis"
        self._cmap_light = "inferno"
        self._colormap_name = self._cmap_dark
        self._data = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._plot = pg.PlotWidget()
        self._plot.setLabel('left', 'Time', units='rows')
        self._plot.setLabel('bottom', 'Frequency', units='Hz')
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.invertY(True)
        _apply_plot_theme(self._plot, "Waterfall", self._dark_bg)
        self._img = pg.ImageItem()
        self._plot.addItem(self._img)
        self._img.setLevels((self._intensity_min, self._intensity_max))
        self._apply_colormap()
        layout.addWidget(self._plot, 1)

        self._toggle_btn = QtWidgets.QToolButton()
        self._toggle_btn.setText("▸")
        self._toggle_btn.setCheckable(True); self._toggle_btn.setChecked(True)
        self._toggle_btn.toggled.connect(self._on_toggle_panel)
        toggle_col = QtWidgets.QVBoxLayout()
        toggle_col.setContentsMargins(0, 0, 0, 0)
        toggle_col.addWidget(self._toggle_btn); toggle_col.addStretch(1)
        toggle_wrap = QtWidgets.QWidget(); toggle_wrap.setLayout(toggle_col)
        layout.addWidget(toggle_wrap)

        self._panel = self._build_panel()
        # Scroll the controls (see FftPlotWidget) so the window can shrink.
        self._panel_scroll = QtWidgets.QScrollArea()
        self._panel_scroll.setWidget(self._panel)
        self._panel_scroll.setWidgetResizable(True)
        self._panel_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._panel_scroll.setVerticalScrollBarPolicy(_VBAR_POLICY)
        self._panel_scroll.verticalScrollBar().setStyleSheet(_SCROLLBAR_QSS)
        self._panel_scroll.setFixedWidth(248)
        self._panel_scroll.setMinimumHeight(80)
        layout.addWidget(self._panel_scroll)

    def _build_panel(self):
        panel = QtWidgets.QGroupBox("Waterfall Controls")
        # Matched with the spectrum panel — see FftPlotWidget._build_panel.
        panel.setFixedWidth(230)
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        ig = QtWidgets.QGroupBox("Intensity")
        igl = QtWidgets.QFormLayout(ig); igl.setContentsMargins(4, 4, 4, 4)
        self._imin_spin = QtWidgets.QDoubleSpinBox(); self._imin_spin.setRange(-300, 100)
        self._imin_spin.setValue(self._intensity_min)
        self._imin_spin.valueChanged.connect(self._on_intensity_changed)
        self._imin_spin.valueChanged.connect(
            lambda v: self.control_changed.emit('intensity_min', v))
        igl.addRow("Min:", self._imin_spin)
        self._imax_spin = QtWidgets.QDoubleSpinBox(); self._imax_spin.setRange(-200, 200)
        self._imax_spin.setValue(self._intensity_max)
        self._imax_spin.valueChanged.connect(self._on_intensity_changed)
        self._imax_spin.valueChanged.connect(
            lambda v: self.control_changed.emit('intensity_max', v))
        igl.addRow("Max:", self._imax_spin)
        auto = QtWidgets.QPushButton("Autoscale intensity")
        auto.clicked.connect(self._on_autoscale_clicked)
        igl.addRow(auto)
        v.addWidget(ig)

        cg = QtWidgets.QGroupBox("Colormap")
        cl = QtWidgets.QVBoxLayout(cg); cl.setContentsMargins(4, 4, 4, 4)
        self._cmap_combo = QtWidgets.QComboBox()
        for n in ["viridis", "plasma", "inferno", "magma", "turbo", "cividis", "gray"]:
            self._cmap_combo.addItem(n)
        self._cmap_combo.setCurrentText(self._colormap_name)
        self._cmap_combo.currentTextChanged.connect(self._on_cmap_changed)
        self._cmap_combo.currentTextChanged.connect(
            lambda s: self.control_changed.emit(f'colormap_{"dark" if self._dark_bg else "light"}', s))
        cl.addWidget(self._cmap_combo)
        v.addWidget(cg)

        dg = QtWidgets.QGroupBox("Display")
        dv = QtWidgets.QVBoxLayout(dg); dv.setContentsMargins(4, 4, 4, 4)
        self._labels_check = QtWidgets.QCheckBox("Axis labels"); self._labels_check.setChecked(True)
        self._labels_check.toggled.connect(self._on_labels_toggled)
        self._labels_check.toggled.connect(
            lambda on: self.control_changed.emit('axis_labels', on))
        dv.addWidget(self._labels_check)
        self._grid_check = QtWidgets.QCheckBox("Grid")
        self._grid_check.toggled.connect(lambda on: self._plot.showGrid(x=on, y=False, alpha=0.3))
        self._grid_check.toggled.connect(
            lambda on: self.control_changed.emit('grid', on))
        dv.addWidget(self._grid_check)
        self._dark_bg_check = QtWidgets.QCheckBox("Dark background")
        self._dark_bg_check.setChecked(self._dark_bg)
        self._dark_bg_check.toggled.connect(self._on_dark_bg_toggled)
        self._dark_bg_check.toggled.connect(
            lambda on: self.control_changed.emit('dark_background', on))
        dv.addWidget(self._dark_bg_check)
        rows_form = QtWidgets.QFormLayout()
        self._rows_spin = QtWidgets.QSpinBox(); self._rows_spin.setRange(32, 4096)
        self._rows_spin.setSingleStep(32); self._rows_spin.setValue(self._rows)
        self._rows_spin.valueChanged.connect(self._on_rows_changed)
        self._rows_spin.valueChanged.connect(
            lambda v: self.control_changed.emit('rows', int(v)))
        rows_form.addRow("Rows:", self._rows_spin)
        dv.addLayout(rows_form)
        v.addWidget(dg)

        v.addStretch(1)
        return panel

    def _apply_colormap(self):
        cm = None
        for source in ('matplotlib', None):
            try:
                cm = pg.colormap.get(self._colormap_name, source=source) if source \
                    else pg.colormap.get(self._colormap_name)
                if cm is not None:
                    break
            except Exception:
                cm = None
        if cm is None:
            try:
                cm = pg.colormap.get('viridis', source='matplotlib')
            except Exception:
                cm = pg.colormap.get('CET-L17')
        lut = cm.getLookupTable(0.0, 1.0, 256)
        self._img.setLookupTable(lut)

    @Slot(object, object, object)
    def on_frame(self, avg_db, _max_db, _min_db):
        n = len(avg_db)
        first_frame = (self._data is None
                       or self._data.shape[1] != n
                       or self._data.shape[0] != self._rows)
        if first_frame:
            self._data = np.full((self._rows, n), self._intensity_min, dtype=np.float32)
        self._data = np.roll(self._data, -1, axis=0)
        self._data[-1, :] = avg_db
        self._img.setImage(self._data, autoLevels=False,
                           levels=(self._intensity_min, self._intensity_max))
        # setRect must run AFTER setImage — pyqtgraph divides by the current
        # image dimensions to derive the affine transform.
        if first_frame:
            self._update_rect()

    def _update_rect(self):
        x0 = self._center_freq - self._samp_rate / 2.0
        x1 = self._center_freq + self._samp_rate / 2.0
        self._img.setRect(QtCore.QRectF(x0, 0.0, x1 - x0, float(self._rows)))

    def set_frequency_range(self, center_freq, bandwidth):
        self._center_freq = float(center_freq)
        self._samp_rate = float(bandwidth)
        if self._data is not None:
            self._update_rect()

    def set_intensity_range(self, lo, hi):
        self._intensity_min = float(lo); self._intensity_max = float(hi)
        self._img.setLevels((lo, hi))
        for spin, val in ((self._imin_spin, lo), (self._imax_spin, hi)):
            spin.blockSignals(True); spin.setValue(val); spin.blockSignals(False)

    def _on_toggle_panel(self, on):
        self._panel_scroll.setVisible(on)
        self._toggle_btn.setText("▸" if on else "◂")

    def _on_intensity_changed(self, _v):
        self._intensity_min = self._imin_spin.value()
        self._intensity_max = self._imax_spin.value()
        self._img.setLevels((self._intensity_min, self._intensity_max))

    def _on_autoscale_clicked(self):
        if self._data is not None:
            lo = float(np.percentile(self._data, 5))
            hi = float(np.percentile(self._data, 99))
            self.set_intensity_range(lo, hi)

    def _on_cmap_changed(self, name):
        self._colormap_name = name
        # Keep the in-memory slot for the current background in sync so a
        # later bg-toggle snapshots correct values.
        if self._dark_bg:
            self._cmap_dark = name
        else:
            self._cmap_light = name
        self._apply_colormap()

    def _on_labels_toggled(self, on):
        self._plot.setLabel('left', 'Time' if on else '', units='rows' if on else '')
        self._plot.setLabel('bottom', 'Frequency' if on else '', units='Hz' if on else '')

    def _on_dark_bg_toggled(self, on):
        # Snapshot the live colormap to the OLD slot, then switch.
        if self._dark_bg:
            self._cmap_dark = self._colormap_name
        else:
            self._cmap_light = self._colormap_name
        self._dark_bg = bool(on)
        _apply_plot_theme(self._plot, "Waterfall", self._dark_bg)
        # Restore the NEW slot's colormap into the live field + UI.
        self._colormap_name = self._cmap_dark if self._dark_bg else self._cmap_light
        with _SignalBlocker(self._cmap_combo):
            self._cmap_combo.setCurrentText(self._colormap_name)
        self._apply_colormap()

    def _on_rows_changed(self, n):
        self._rows = int(n)
        self._data = None

    def apply_settings(self, settings):
        """Push every value from the waterfall section of `settings` into the UI."""
        section = 'waterfall'
        # Load both per-background colormap slots so toggling is instant.
        self._cmap_dark = settings.get_str(section, 'colormap_dark')
        self._cmap_light = settings.get_str(section, 'colormap_light')

        with _SignalBlocker(self._imin_spin, self._imax_spin, self._cmap_combo,
                            self._labels_check, self._grid_check, self._dark_bg_check,
                            self._rows_spin):
            self._imin_spin.setValue(settings.get_float(section, 'intensity_min'))
            self._imax_spin.setValue(settings.get_float(section, 'intensity_max'))
            self._labels_check.setChecked(settings.get_bool(section, 'axis_labels'))
            self._grid_check.setChecked(settings.get_bool(section, 'grid'))
            self._dark_bg_check.setChecked(settings.get_bool(section, 'dark_background'))
            self._rows_spin.setValue(settings.get_int(section, 'rows'))
            # Colormap combo follows the active slot.
            self._dark_bg = self._dark_bg_check.isChecked()
            self._colormap_name = self._cmap_dark if self._dark_bg else self._cmap_light
            self._cmap_combo.setCurrentText(self._colormap_name)
        # Apply effects normally triggered by the blocked signals.
        self._intensity_min = self._imin_spin.value()
        self._intensity_max = self._imax_spin.value()
        self._img.setLevels((self._intensity_min, self._intensity_max))
        self._apply_colormap()
        self._on_labels_toggled(self._labels_check.isChecked())
        self._plot.showGrid(x=self._grid_check.isChecked(), y=False, alpha=0.3)
        _apply_plot_theme(self._plot, "Waterfall", self._dark_bg)
        self._rows = self._rows_spin.value()
        self._data = None  # force waterfall to re-init at the new row count


class Range:
    """Tiny replacement for qtgui.Range — just a record."""
    def __init__(self, rmin, rmax, step, default, nsteps):
        self.min = rmin; self.max = rmax
        self.step = step; self.default = default; self.nsteps = nsteps


class RangeWidget(QtWidgets.QWidget):
    """Drop-in replacement for qtgui.RangeWidget. Signature matches:
        RangeWidget(range_obj, callback, label, style, value_type, orientation)
    where range_obj exposes .min/.max/.step/.default/.nsteps. Calls
    callback(value_type(v)) when the user edits the value."""

    def __init__(self, range_obj, callback, label, style="counter_slider",
                 value_type=float, orientation=Qt.Horizontal, parent=None):
        super().__init__(parent)
        rmin, rmax, rstep, rdefault, _ = (range_obj.min, range_obj.max,
                                          range_obj.step, range_obj.default,
                                          range_obj.nsteps)
        self._callback = callback
        self._type = value_type
        self._rmin = float(rmin); self._rmax = float(rmax)
        self._rstep = float(rstep) if rstep > 0 else (self._rmax - self._rmin) / 100.0

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2); layout.setHorizontalSpacing(6)
        layout.addWidget(QtWidgets.QLabel(label + ":"), 0, 0)

        if value_type is int:
            self._spin = QtWidgets.QSpinBox()
            self._spin.setRange(int(rmin), int(rmax))
            self._spin.setSingleStep(max(1, int(self._rstep)))
            self._spin.setValue(int(rdefault))
        else:
            self._spin = QtWidgets.QDoubleSpinBox()
            self._spin.setRange(self._rmin, self._rmax)
            self._spin.setSingleStep(self._rstep)
            self._spin.setDecimals(self._decimals_for(self._rstep))
            self._spin.setValue(float(rdefault))
        layout.addWidget(self._spin, 0, 1)

        self._steps = max(100, int((self._rmax - self._rmin) / self._rstep))
        self._slider = QtWidgets.QSlider(orientation)
        self._slider.setRange(0, self._steps)
        self._slider.setValue(self._v_to_s(float(rdefault)))
        layout.addWidget(self._slider, 1, 0, 1, 2)

        self._updating = False
        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)

    @staticmethod
    def _decimals_for(step):
        if step >= 1:
            return 0
        s = f"{step:.10f}".rstrip('0').rstrip('.')
        return min(6, len(s.split('.')[1])) if '.' in s else 0

    def _v_to_s(self, v):
        if self._rmax == self._rmin:
            return 0
        frac = (v - self._rmin) / (self._rmax - self._rmin)
        return int(round(frac * self._steps))

    def _s_to_v(self, s):
        frac = s / self._steps if self._steps else 0
        return self._rmin + frac * (self._rmax - self._rmin)

    def _on_slider(self, s):
        if self._updating: return
        self._updating = True
        v = self._s_to_v(s)
        if self._type is int:
            v = int(round(v))
        self._spin.setValue(v)
        self._updating = False
        self._emit(v)

    def _on_spin(self, v):
        if self._updating: return
        self._updating = True
        self._slider.setValue(self._v_to_s(float(v)))
        self._updating = False
        self._emit(v)

    def _emit(self, v):
        try:
            self._callback(self._type(v))
        except Exception as exc:
            print(f"RangeWidget callback failed: {exc}", file=sys.stderr)

    def set_value(self, v):
        self._updating = True
        if self._type is int:
            self._spin.setValue(int(v))
        else:
            self._spin.setValue(float(v))
        self._slider.setValue(self._v_to_s(float(v)))
        self._updating = False


# === Device discovery + picker ===

# When resolve_device_serial returns this sentinel, the main class builds a
# SigMF-playback flowgraph instead of opening a USRP. The sample files
# (sample.sigmf-data, sample.sigmf-meta) ship in the release bundle and live
# next to dses_spectrum_analyzer.py.
PLAYBACK_SENTINEL = "__PLAYBACK__"
SIGMF_SAMPLE_BASENAME = "sample"


def find_default_sample_path():
    """Locate the bundled SigMF sample. Returns the basename path (no
    extension) if both .sigmf-data and .sigmf-meta exist next to this
    source file, otherwise None."""
    here = Path(__file__).resolve().parent
    base = here / SIGMF_SAMPLE_BASENAME
    if base.with_suffix('.sigmf-data').is_file() and \
       base.with_suffix('.sigmf-meta').is_file():
        return str(base)
    return None


def load_sigmf_meta(base_path):
    """Read .sigmf-meta JSON next to base_path. Returns (sample_rate_hz,
    center_freq_hz, datatype) or raises on malformed metadata."""
    import json
    with open(base_path + '.sigmf-meta', encoding='utf-8') as f:
        meta = json.load(f)
    g = meta.get('global', {})
    sr = float(g['core:sample_rate'])
    dtype = g.get('core:datatype', 'cf32_le')
    caps = meta.get('captures', [])
    cf = float(caps[0].get('core:frequency', 0)) if caps else 0.0
    return sr, cf, dtype


def _addr_to_dict(a):
    """Pull serial/product/name out of a uhd device_addr object. to_dict()
    has been observed to return {} in some Python contexts even when the
    string form has full info, so we fall back to parsing str(a)."""
    # Try to_dict / dict first.
    for fn in ((lambda: a.to_dict()),
               (lambda: {k: a.get(k) for k in a.keys()}),
               (lambda: dict(a))):
        try:
            d = fn()
            if d:
                return d
        except Exception:
            continue
    # Last resort: parse the "Device Address:\n    key: value\n..." string.
    d = {}
    for line in str(a).splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            d[k.strip()] = v.strip()
    return d


# Driver identifiers used internally. Settings store the chosen one in
# [rx]/device_driver and the corresponding serial in [rx]/device_serial.
DRIVER_UHD_B200 = "uhd_b200"

# Soapy drivers we surface to the picker. Anything not in this list is
# still enumerable via SoapySDR.Device.enumerate() with no filter, but we
# only advertise these to avoid showing internal/loopback adapters.
SOAPY_KNOWN_DRIVERS = ("sdrplay", "rtlsdr", "hackrf", "airspy",
                       "airspyhf", "bladerf", "lime", "plutosdr")


def find_b200_uhd():
    """Return UHD B200-family devices as {driver, serial, product, label}."""
    try:
        addrs = uhd.find('type=b200')
    except Exception as exc:
        print(f"UHD discovery failed: {exc}", file=sys.stderr)
        return []
    out = []
    for a in addrs:
        d = _addr_to_dict(a)
        serial = d.get('serial', '')
        product = d.get('product', d.get('type', 'B200'))
        out.append({
            'driver':  DRIVER_UHD_B200,
            'serial':  serial,
            'product': product,
            'label':   f"USRP {product} — {serial or '(no serial)'}",
        })
    return out


def find_soapy_devices():
    """Return SoapySDR devices (RSPx, RTL-SDR, HackRF, …) as
    {driver, serial, product, label}. Skipped silently if SoapySDR isn't
    importable."""
    try:
        import SoapySDR
    except Exception:
        return []
    # Enumerate each known driver explicitly rather than calling
    # SoapySDR.Device.enumerate() with no args. A no-arg enumerate also runs
    # the bundled "remote" module's discovery, which pings IPv6 SSDP
    # multicast and logs a noisy (benign) ERROR on hosts with no IPv6 route.
    # Per-driver enumeration only invokes the driver we ask for, so that
    # network scan never happens.
    out = []
    for drv in SOAPY_KNOWN_DRIVERS:
        try:
            addrs = SoapySDR.Device.enumerate(f"driver={drv}")
        except Exception as exc:
            print(f"SoapySDR discovery failed for {drv}: {exc}",
                  file=sys.stderr)
            continue
        for a in addrs:
            try:
                d = dict(a)
            except Exception:
                continue
            # Each Soapy driver names its serial field differently. Try the
            # common keys; fall back to the driver name + index for display.
            serial = (d.get('serial') or d.get('serial_number')
                      or d.get('device_id') or '')
            product = (d.get('label') or d.get('product')
                       or d.get('hardware') or drv)
            # SDRPlay-specific: SoapySDR's label is "SDRplay Dev{N} {model} {serial}"
            # (sometimes with a colon, sometimes without). Strip the prefix and
            # the trailing duplicate serial so we keep only the model, e.g. "RSP1B".
            if drv == 'sdrplay':
                m = re.match(
                    r'^SDRplay\s+Dev\d+:?\s+(?P<model>\S+)(?:\s+\S+)?\s*$',
                    product, re.IGNORECASE)
                if m:
                    product = m.group('model')
            out.append({
                'driver':  drv,
                'serial':  serial,
                'product': product,
                'label':   f"{product} — {serial or '(no serial)'}  [{drv}]",
            })
    return out


def find_all_radios():
    """Combined enumeration of every supported SDR backend."""
    return find_b200_uhd() + find_soapy_devices()


def _bring_to_front(win):
    """Raise/activate a top-level window so it opens in front. On macOS an app
    launched from a terminal opens its windows behind the terminal until the
    app is activated; this makes startup dialogs and the main window visible
    immediately. It doesn't pin them on top afterward.

    Also clears an inherited *minimized* state: the Windows launcher starts the
    process with its console minimized to keep it out of the way, and Qt's
    first top-level window inherits that show-state — so without this the
    spectrum window itself would open minimized. Only the console should stay
    minimized; the GUI should be visible."""
    try:
        if win.windowState() & Qt.WindowMinimized:
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
        win.raise_()
        win.activateWindow()
    except Exception:
        pass


def _make_int_spinbox(lo, hi, value, tooltip):
    """A QSpinBox that reliably shows its initial value on every platform.

    Windows quirk: when setValue() is a no-op because `value` already equals
    the range minimum (a fresh spinbox's default 0 is clamped up to the minimum
    by setRange), the embedded line edit is never refreshed and the field
    renders BLANK — while macOS shows it fine. Force the editor text so the
    value is always visible. (This is the Integrate field, whose default is 1 =
    its minimum.)"""
    s = QtWidgets.QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    le = s.lineEdit()
    if le is not None:
        le.setText(s.textFromValue(s.value()))
    s.setToolTip(tooltip)
    return s


def _front_messagebox(parent, icon, title, text):
    """Modal message box that opens in front of everything — including another
    app's windows (e.g. the Terminal that launched us on macOS, where a
    plain raise_() isn't enough to clear another application). The stay-on-top
    flag floats it above the terminal; it's dismissed immediately so it
    doesn't linger on top."""
    box = QtWidgets.QMessageBox(icon, title, text,
                                QtWidgets.QMessageBox.Ok, parent)
    box.setWindowModality(Qt.ApplicationModal)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    box.show()
    _bring_to_front(box)
    return box.exec()


class DevicePickerDialog(QtWidgets.QDialog):
    """Modal dialog listing every attached SDR. selected_device() returns
    the picked device dict (with 'driver' and 'serial' keys); Cancel
    returns None."""

    def __init__(self, devices, current_driver=None, current_serial=None,
                 parent=None, prompt="Pick a radio to use:"):
        super().__init__(parent)
        self.setWindowTitle("Choose Radio")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # float above the terminal
        self.setMinimumWidth(460)
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel(prompt))

        self._list = QtWidgets.QListWidget()
        font = QtGui.QFont("Courier New", 10)
        font.setStyleHint(QtGui.QFont.Monospace)
        self._list.setFont(font)
        for dev in devices:
            item = QtWidgets.QListWidgetItem(dev['label'])
            item.setData(Qt.UserRole, dev)
            self._list.addItem(item)
            if (dev['driver'] == current_driver
                    and dev['serial'] == (current_serial or '')):
                self._list.setCurrentItem(item)
        if self._list.currentItem() is None and self._list.count() > 0:
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout.addWidget(self._list)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_device(self):
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def showEvent(self, event):
        super().showEvent(event)
        _bring_to_front(self)


def resolve_device(saved_driver, saved_serial, parent=None):
    """Decide which SDR to open. Returns one of:
        - a device dict {driver, serial, product, label}
        - PLAYBACK_SENTINEL if no device is attached but the bundled SigMF
          sample is present
        - None if the user canceled the picker and there's nothing to fall
          back on.
    Selection rule: no radio → playback/error; exactly one radio → use it
    silently; two or more radios → always show the picker so the user
    chooses, pre-selecting the saved (driver, serial) from settings.
    `saved_driver` and `saved_serial` come from settings."""
    devices = find_all_radios()

    if not devices:
        sample = find_default_sample_path()
        if sample is None:
            _front_messagebox(
                parent, QtWidgets.QMessageBox.Critical, "No radio found",
                "No supported SDR was detected (looked for UHD B200/B210 and "
                "SoapySDR-recognised devices: SDRPlay, RTL-SDR, HackRF, "
                "Airspy, BladeRF, Lime, PlutoSDR), and no bundled SigMF "
                "sample file was found next to the program.\n\n"
                "Plug a supported radio in and relaunch, or place "
                f"'{SIGMF_SAMPLE_BASENAME}.sigmf-data' and "
                f"'{SIGMF_SAMPLE_BASENAME}.sigmf-meta' alongside "
                "dses_spectrum_analyzer.py to enable demo playback.")
            return None
        _front_messagebox(
            parent, QtWidgets.QMessageBox.Information, "Playback mode",
            "No radio detected — starting in SigMF playback mode.\n\n"
            f"File: {Path(sample).name}.sigmf-data\n\n"
            "The sample loops continuously. Sample rate, gain, and recording "
            "are disabled (no hardware). Tuning is enabled and digitally "
            "shifts the spectrum within the recording's bandwidth — tune "
            "outside it and you'll just see noise.")
        return PLAYBACK_SENTINEL

    saved_driver = (saved_driver or '').strip()
    saved_serial = (saved_serial or '').strip()
    # Backwards-compat: pre-v1.0.0 INIs only had device_serial; assume B210.
    if saved_serial and not saved_driver:
        saved_driver = DRIVER_UHD_B200

    # Exactly one radio attached → use it silently.
    if len(devices) == 1:
        return devices[0]

    # Two or more radios attached → always let the user choose. The saved
    # (driver, serial) is pre-selected in the picker, so the common case is
    # a single Enter to confirm the same radio as last time.
    dlg = DevicePickerDialog(devices, current_driver=saved_driver,
                             current_serial=saved_serial, parent=parent)
    if dlg.exec() == QtWidgets.QDialog.Accepted:
        return dlg.selected_device()
    return None


# === About + Help dialogs ===

class AboutDialog(QtWidgets.QDialog):
    """Version, author, license, dependencies, plus the Restore Defaults
    button. Defaults wipes the settings file back to built-ins and emits
    `defaults_requested` so the main window can re-apply across all widgets."""

    defaults_requested = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(480)

        layout = QtWidgets.QVBoxLayout(self)

        # Header
        title = QtWidgets.QLabel(f"<h2>{APP_NAME}</h2>"
                                 f"<p>Version <b>{APP_VERSION}</b></p>")
        title.setTextFormat(Qt.RichText)
        layout.addWidget(title)

        info = QtWidgets.QLabel(
            f"<p>{APP_DESCRIPTION}</p>"
            f"<p><b>Author:</b> {APP_AUTHOR} &lt;{APP_AUTHOR_EMAIL}&gt;<br>"
            f"<b>{APP_COPYRIGHT}</b><br>"
            f"<b>License:</b> {APP_LICENSE}</p>"
            f"<p>This program is free software: you can redistribute it and/or "
            f"modify it under the terms of the GNU General Public License as "
            f"published by the Free Software Foundation, either version 3 of "
            f"the License, or (at your option) any later version. See the "
            f"LICENSE file for the full text.</p>"
            f"<p><b>Built on:</b> GNU Radio · UHD · SoapySDR · PySide6 · "
            f"PyQtGraph · NumPy · SciPy</p>"
            f"<p><b>Settings file:</b><br><code>{settings.path}</code></p>"
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(info)

        # Buttons
        btn_row = QtWidgets.QHBoxLayout()
        defaults_btn = QtWidgets.QPushButton("Restore Defaults…")
        defaults_btn.setToolTip("Reset every setting to its built-in default. "
                                "The settings file is overwritten.")
        defaults_btn.clicked.connect(self._on_defaults_clicked)
        btn_row.addWidget(defaults_btn)
        open_btn = QtWidgets.QPushButton("Open Settings Folder")
        open_btn.clicked.connect(self._on_open_settings_folder)
        btn_row.addWidget(open_btn)
        btn_row.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_defaults_clicked(self):
        ans = QtWidgets.QMessageBox.question(
            self, "Restore Defaults",
            "This will reset every setting to its built-in default and "
            "overwrite the settings file. Continue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if ans == QtWidgets.QMessageBox.Yes:
            self._settings.reset_to_defaults()
            self.defaults_requested.emit()
            QtWidgets.QMessageBox.information(
                self, "Defaults restored",
                "Settings have been reset to their built-in values.")

    def _on_open_settings_folder(self):
        folder = str(self._settings.path.parent)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))


HELP_TEXT_HTML = f"""
<h2>{APP_NAME} — User Guide</h2>

<p>This is a live spectrum analyzer and waterfall display for the Ettus USRP
B210 and other software-defined radios (SDRPlay RSP1A/RSP1B/RSPduo/RSPdx,
RTL-SDR, HackRF, Airspy, BladeRF, LimeSDR, PlutoSDR via SoapySDR), designed
for pulsar RFI investigation but useful for general-purpose spectrum
monitoring.</p>

<h3>Starting up — device selection</h3>
<p>At launch the program enumerates attached SDRs (UHD + SoapySDR) and
decides what to use:</p>
<ul>
<li><b>One supported SDR attached</b>: opens it silently and remembers the
driver and serial in the settings file.</li>
<li><b>Two or more radios attached</b>: a picker dialog always appears so
you can choose which one to use. Your previous choice is pre-selected, so
you can just press Enter to use the same radio as last time. Your selection
is remembered for next launch.</li>
<li><b>No SDR attached, but a bundled SigMF sample is present</b>: the
program falls back to <b>playback mode</b> — see below.</li>
<li><b>No SDR and no sample</b>: an error dialog explains how to fix it
and the program exits.</li>
</ul>
<p>The window title always shows which radio is feeding the display, and
the <b>RX</b> group has a <code>Device:</code> button you can click to
re-open the picker. The new choice takes effect on the next launch.</p>

<h3>Playback mode</h3>
<p>If no SDR is attached, the program looks next to the application file
for <code>sample.sigmf-data</code> + <code>sample.sigmf-meta</code> and, if
both are found, plays the file back in a continuous loop. The window title
shows <b>[Playback]</b>. The data source is the file, paced to the original
capture's sample rate.</p>
<ul>
<li><b>Sample Rate</b>, <b>RX Gain</b>, and <b>Recording</b> controls are
disabled — they have no meaning for a recorded file. Sample rate comes
from the file's metadata.</li>
<li><b>Tuning is enabled</b> and works as a digital frequency shift
(<code>blocks.rotator_cc</code>) on the file's baseband. Tuning to the
file's actual center frequency (read from the .sigmf-meta) shows the
recording's true content; tuning to other frequencies within
±(sample_rate/2) of the file's center lets you "look around" inside the
recorded bandwidth. Tune well outside that window and you'll just see
noise / wrap-around — exactly what you'd expect, since the recording
doesn't contain data at those frequencies.</li>
<li>All visualization controls (Spectrum panel, Waterfall panel) work
normally.</li>
<li>To replace the sample with your own, save a SigMF recording, rename the
two files to <code>sample.sigmf-data</code> and <code>sample.sigmf-meta</code>,
and drop them next to the program. (You don't need to change any code.)</li>
</ul>

<h3>Sidebar controls (right side)</h3>
<h4>Tuning</h4>
<ul>
<li><b>Pulsar Band</b>: preset frequencies for common pulsar observation
bands. Choose <i>Manual</i> to use the Manual Frequency field instead.</li>
<li><b>Coarse Tune</b>: ±100 MHz offset from the selected preset (or from
the manual frequency).</li>
<li><b>Fine Tune</b>: ±10 MHz offset, layered on top of Coarse Tune.</li>
<li><b>Manual Frequency</b>: used when the <i>Manual</i> preset is selected.
Accepts engineering notation, e.g. <code>1.42G</code> or <code>408M</code>.</li>
</ul>

<h4>RX</h4>
<ul>
<li><b>Sample Rate</b>: per-radio. The combo shows validated quick-pick rates
for the connected radio (e.g. B210: 0.625–25 MHz; SDRPlay: 2–10 MHz; RTL-SDR:
0.25–3.2 MHz). Higher rate = wider spectrum but more disk usage when
recording.</li>
<li><b>Manual Rate (Hz)</b>: type any rate the SDR supports — useful for
real-pulsar capture geometries that aren't in the preset list. The value is
clamped to the device's reported min/max (hover for the range) and the radio
snaps to the nearest rate it can actually deliver, which is then shown back.
Accepts engineering notation (e.g. <code>24M</code>, <code>625k</code>). The
combo clears when the active rate isn't one of the presets.</li>
<li><b>RX Gain</b>: per-radio range and meaning. The slider's min/max
matches what the driver reports (e.g. B210: 0–76 dB on the AD9361 gain
table; SDRPlay: 0–48 dB, internally inverted so higher = stronger signal;
RTL-SDR: 0–49.6 dB). AGC, if the driver defaults it on, is disabled at
startup so the slider always takes effect.</li>
<li><b>Antenna</b>: appears only when the open radio has more than one RF
input. For a B210 this lists all four physical connectors as
<code>A : RX2</code>, <code>A : TX/RX</code>, <code>B : RX2</code>,
<code>B : TX/RX</code> — receiver A and receiver B, each with its two SMA
ports — and switching includes hopping between the two receivers. An
RSPduo lists its two tuners. Pick the connector your cable is actually
plugged into; the choice is remembered per radio. Single-port radios (most
RTL dongles, the RSP1B) don't show this control.</li>
<li><b>Device</b>: shows the currently-open radio and re-opens the picker
on click.</li>
</ul>

<h4>Recording</h4>
<ul>
<li><b>Folder</b>: where recordings land. Defaults to
<code>~/Documents/DSES_SA_Recordings</code>.</li>
<li><b>Format</b>: <i>Raw I/Q (SigMF)</i> writes full-rate complex samples to
a SigMF <code>.sigmf-meta</code>/<code>.sigmf-data</code> pair — exact, but
large (e.g. ~192&nbsp;MB/s at 24&nbsp;Msps). <i>Filterbank (.fil)</i>
channelizes the stream live and writes a SIGPROC filterbank
(<code>telescope_id&nbsp;12</code>) straight to disk, so the giant raw I/Q is
never stored. The <code>.fil</code> is what PRESTO folds; it is produced by
the same validated code as the offline <code>iq_to_fil.py</code> converter.</li>
<li><b>Channels</b> / <b>Integrate</b> (filterbank only): the FFT channel
count and how many power frames are summed per output sample, so
<code>tsamp&nbsp;=&nbsp;channels&nbsp;&times;&nbsp;integrate&nbsp;/&nbsp;sample&nbsp;rate</code>.
Locked while recording.</li>
<li><b>Record</b>: <i>Stopped</i> / <i>Recording</i>. Recording always
starts <i>Stopped</i> on launch.</li>
</ul>

<h3>Spectrum (top plot)</h3>
<p>Live FFT magnitude in dB. Use the control panel on the right side to
adjust:</p>
<ul>
<li><b>FFT Size</b>: 256–8192. Larger = finer frequency resolution but
slower response and more averaging-window flicker.</li>
<li><b>Window</b>: Blackman-Harris is the default — low sidelobes, good
for RFI hunting. Hann/Hamming have narrower main lobes; Rectangular has
the sharpest peak but the worst sidelobes.</li>
<li><b>Avg α</b>: exponential averaging. 1.0 = no smoothing (every frame
is a fresh measurement). Smaller = more smoothing.</li>
<li><b>Max / Min hold</b>: overlay traces showing the highest/lowest value
ever seen at each bin. Use <b>Reset</b> to clear.</li>
<li><b>Y-Axis</b>: dB min/max, or click <b>Autoscale</b> to fit the
current data. <b>Reset Axes</b> snaps the plot back to the default dB range
and full-span frequency view — handy after you've zoomed/panned with the
mouse or nudged the min/max and want to get un-lost. It leaves FFT size,
window, traces, and colors untouched.</li>
<li><b>Linear scale</b>: plots linear magnitude instead of dB (the default
log scale). In linear mode the Y axis auto-fits and the dB Min/Max boxes are
disabled. Affects the spectrum plot only — the waterfall stays in dB.</li>
<li><b>Trace</b>: color, line width, alpha, label.</li>
</ul>

<h3>Waterfall (bottom plot)</h3>
<p>Scrolling 2-D image of FFT vs. time. Newest row at the bottom.</p>
<ul>
<li><b>Intensity Min/Max</b>: dB range that maps to the colormap.
<b>Autoscale intensity</b> picks the 5%–99% percentile of the current
data.</li>
<li><b>Colormap</b>: viridis (default), plasma, inferno, magma, turbo,
cividis, gray.</li>
<li><b>Rows</b>: how many history rows to display (default 256).</li>
</ul>

<h3>Persistence</h3>
<p>All selections are saved to a plain-text INI file and restored on next
launch. The file location is shown in <b>Help → About</b>; you can open
the folder directly with the <b>Open Settings Folder</b> button.</p>
<p>To revert everything to factory defaults, use <b>Restore Defaults</b>
in the About dialog.</p>

<h3>Update checks</h3>
<p>If the developer has configured a manifest URL, the program checks for
a newer release in the background at launch (no more than once every 24
hours). When a newer version is found, a non-modal dialog opens with the
release notes and a button that opens the download page in your browser —
you can ignore it and keep using the app, or click <b>Skip this version</b>
to not be reminded about that particular version again.</p>
<p>The check is read-only and never auto-downloads or auto-installs. To
trigger a check manually, use <b>Help → Check for Updates…</b>. To disable
auto-checks, set <code>auto_check = false</code> under <code>[updates]</code>
in the settings file. If the manifest URL has not been configured yet, the
auto-check is silently skipped.</p>

<h3>Tips for pulsar work</h3>
<ul>
<li>1422 MHz preset is centered on the neutral-hydrogen line (HI).</li>
<li>1666 MHz preset covers the OH maser band.</li>
<li>Use <b>Avg α</b> ≈ 0.05 and <b>Max hold</b> to find intermittent
RFI sources.</li>
<li>The waterfall reveals time-structured interference (e.g. radar sweeps,
ADS-B bursts) that the live spectrum smears out.</li>
</ul>
"""


class HelpDialog(QtWidgets.QDialog):
    """Scrollable user guide. Read-only HTML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — User Guide")
        self.resize(700, 600)

        layout = QtWidgets.QVBoxLayout(self)

        text = QtWidgets.QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml(HELP_TEXT_HTML)
        layout.addWidget(text, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# === Overflow capture (UHD and gr-soapy write 'O' to FD-level stderr on RX overflow) ===

# Match runs of bare 'O' characters that aren't part of a word (so "OOO"
# scrolls past, but normal stderr text like "Operating" or "Boost_108600"
# is ignored).
_OVERFLOW_RE = re.compile(r'\bO+\b')


class OverflowMonitor(QtCore.QObject):
    """Redirects FD 2 (C-level stderr) into a pipe, scans the byte stream
    for RX overflow indicators ('O' characters, written by both UHD and
    gr-soapy), and emits them via a Qt signal. All stderr output is passed
    through to the original console unchanged, so info logs and tracebacks
    still appear there."""

    chars_received = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stopped = False
        self._saved_stderr_fd = -1
        self._read_fd = -1
        self._write_fd = -1
        self._reader_thread = None

    def start(self):
        try:
            sys.stderr.flush()
        except Exception:
            pass
        self._read_fd, self._write_fd = os.pipe()
        self._saved_stderr_fd = os.dup(2)
        os.dup2(self._write_fd, 2)
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="stderr-overflow-monitor", daemon=True)
        self._reader_thread.start()

    def stop(self):
        self._stopped = True
        # Restore the real stderr so any shutdown messages go to the console,
        # then close the pipe so the reader thread can exit.
        if self._saved_stderr_fd >= 0:
            try:
                os.dup2(self._saved_stderr_fd, 2)
            except OSError:
                pass
        if self._write_fd >= 0:
            try:
                os.close(self._write_fd)
            except OSError:
                pass
            self._write_fd = -1

    def _reader_loop(self):
        try:
            while not self._stopped:
                try:
                    data = os.read(self._read_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                # Pass-through to the real console.
                if self._saved_stderr_fd >= 0:
                    try:
                        os.write(self._saved_stderr_fd, data)
                    except OSError:
                        pass
                # Extract standalone 'O' runs.
                text = data.decode('utf-8', errors='replace')
                matches = _OVERFLOW_RE.findall(text)
                if matches:
                    # AutoConnection → QueuedConnection across threads, so the
                    # slot runs on the GUI thread safely.
                    self.chars_received.emit(''.join(matches))
        except Exception:
            # Never let the reader thread propagate exceptions to nothing.
            pass


class OverflowDisplayWidget(QtWidgets.QGroupBox):
    """Sidebar group that streams RX overflow 'O' characters into a fixed
    4-line text view. Both UHD and gr-soapy print 'O' to stderr when the
    host can't drain samples fast enough, so this works for any radio.
    Older lines are auto-dropped by Qt itself via `setMaximumBlockCount`,
    so the widget never grows past 4 lines and there's nothing to scroll."""

    MAX_LINES = 4
    LINE_WIDTH = 40  # chars per logical line — fits the narrowest sidebar
    IDLE_CLEAR_MS = 15000  # auto-clear if no new overflow chars for this long

    def __init__(self, parent=None):
        super().__init__("Overflow ('O' = dropped samples)", parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        # NoWrap + explicit '\n' every LINE_WIDTH chars → each block is one
        # visual line. setMaximumBlockCount then caps history at MAX_LINES;
        # Qt drops the oldest block when we add a 5th, no scroll needed.
        self._text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text.setMaximumBlockCount(self.MAX_LINES)
        self._text.setFixedHeight(64)
        font = QtGui.QFont("Courier New", 10)
        font.setStyleHint(QtGui.QFont.Monospace)
        self._text.setFont(font)
        self._text.setPlaceholderText("(no overflows)")
        layout.addWidget(self._text)

        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        layout.addWidget(clear_btn)

        # Chars currently on the bottom line; reset to 0 each time we wrap.
        self._line_chars = 0

        # Single-shot timer restarted on every emit. When it fires, no new
        # overflow chars have arrived for IDLE_CLEAR_MS — wipe the display.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self.IDLE_CLEAR_MS)
        self._idle_timer.timeout.connect(self.clear)

    @Slot(str)
    def append_chars(self, s):
        if not s:
            return
        # Cursor-based incremental insert — much cheaper than setPlainText,
        # which would re-lay out the whole document on every emit and caused
        # the freeze/jitter at high overflow rates.
        cursor = self._text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        remaining = s
        while remaining:
            free = self.LINE_WIDTH - self._line_chars
            if free <= 0:
                cursor.insertText('\n')
                self._line_chars = 0
                free = self.LINE_WIDTH
            chunk = remaining[:free]
            cursor.insertText(chunk)
            self._line_chars += len(chunk)
            remaining = remaining[free:]
        # Keep the view pinned to the newest line.
        self._text.moveCursor(QtGui.QTextCursor.End)
        # Restart the idle-clear countdown.
        self._idle_timer.start()

    @Slot()
    def clear(self):
        self._text.clear()
        self._line_chars = 0
        self._idle_timer.stop()


# === Auto-update check ===

def _parse_version(v):
    """Parse a dotted version string into a tuple of ints. Returns () on
    parse failure (which compares as 'lower than anything')."""
    try:
        return tuple(int(p) for p in str(v).split('.'))
    except (ValueError, TypeError):
        return ()


class UpdateChecker(QtCore.QObject):
    """Fetches a small manifest.json from a configured URL on a background
    thread and, if it advertises a newer version than what's running, emits
    `update_available(latest_version, download_url, release_notes)`. Errors
    are reported via `check_failed(message)` — auto-launches ignore them,
    manual 'Check now' surfaces them."""

    update_available = Signal(str, str, str)  # version, url, notes
    no_update = Signal(str)                   # latest_version
    check_failed = Signal(str)                # human-readable message

    USER_AGENT = f"{APP_NAME}/{APP_VERSION}"

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings

    @Slot()
    def check_now(self):
        threading.Thread(target=self._do_check, name="update-checker",
                         daemon=True).start()

    def _do_check(self):
        url = self._settings.get_str('updates', 'manifest_url').strip()
        if not url:
            # Not configured — silently skip. Manual 'Check for Updates'
            # menu handler should also check this and tell the user.
            return
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = resp.read()
            import json
            data = json.loads(raw.decode('utf-8'))
        except Exception as exc:
            self.check_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        latest = str(data.get('latest_version', '')).strip()
        download_url = str(data.get('download_url', '')).strip()
        notes = str(data.get('release_notes', '')).strip()
        if not latest:
            self.check_failed.emit("Manifest has no 'latest_version' field.")
            return
        # Remember the last successful check so we can debounce repeats.
        self._settings.set('updates', 'last_check_iso',
                           datetime.now().isoformat(timespec='seconds'))
        try:
            self._settings.save()
        except OSError:
            pass
        if _parse_version(latest) > _parse_version(APP_VERSION):
            self.update_available.emit(latest, download_url, notes)
        else:
            self.no_update.emit(latest)


def _guide_url_from_download(download_url):
    """Derive the install/upgrade guide PDF URL from a release zip URL: the
    guide sits next to the zips in the same server folder. Returns "" if the
    download URL is empty/unusable."""
    download_url = (download_url or "").strip()
    if "/" not in download_url:
        return ""
    folder = download_url.rsplit("/", 1)[0]
    return f"{folder}/{GUIDE_PDF_BASENAME}"


class UpdateNotificationDialog(QtWidgets.QDialog):
    """Non-modal: tells the user a new version is available. It steers them to
    the install/upgrade *guide* first, then offers the download zip, skip, or
    close. Emits `dismissed_for_version(version)` if the user clicks Skip."""

    dismissed_for_version = Signal(str)

    def __init__(self, latest_version, download_url, release_notes,
                 current_version, parent=None):
        super().__init__(parent)
        # Non-modal so the user can keep using the app.
        self.setModal(False)
        self.setWindowTitle("Update Available")
        self.setMinimumWidth(500)

        self._latest = latest_version
        self._url = download_url
        self._guide_url = _guide_url_from_download(download_url)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            f"<h3>Version {latest_version} is available.</h3>"
            f"<p>You're running version {current_version}.</p>"))

        # Steer the user to the guide BEFORE the zip: the zip is not a
        # double-click installer — it must be applied per the guide.
        layout.addWidget(QtWidgets.QLabel(
            "<p><b>Read the installation &amp; upgrade guide first.</b> The "
            "download is a <code>.zip</code> of program files, not an "
            "installer — the guide explains how to apply it safely (where to "
            "unzip, what to replace, and not to reinstall Radioconda).</p>"))

        if release_notes:
            notes = QtWidgets.QTextEdit()
            notes.setReadOnly(True)
            notes.setPlainText(release_notes)
            notes.setFixedHeight(140)
            layout.addWidget(QtWidgets.QLabel("<b>Release notes:</b>"))
            layout.addWidget(notes)

        if download_url:
            url_lbl = QtWidgets.QLabel(f"Download: <code>{download_url}</code>")
            url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            url_lbl.setWordWrap(True)
            layout.addWidget(url_lbl)

        btns = QtWidgets.QHBoxLayout()
        # Primary action: open the guide (the "read me first" step).
        guide_btn = QtWidgets.QPushButton("Read the Guide (PDF)")
        guide_btn.setEnabled(bool(self._guide_url))
        guide_btn.setDefault(True)
        guide_btn.clicked.connect(self._on_guide)
        btns.addWidget(guide_btn)

        dl_btn = QtWidgets.QPushButton("Download Update (.zip)")
        dl_btn.setEnabled(bool(download_url))
        dl_btn.clicked.connect(self._on_open)
        btns.addWidget(dl_btn)

        skip_btn = QtWidgets.QPushButton("Skip This Version")
        skip_btn.clicked.connect(self._on_skip)
        btns.addWidget(skip_btn)

        btns.addStretch(1)

        remind_btn = QtWidgets.QPushButton("Remind Me Later")
        remind_btn.clicked.connect(self.close)
        btns.addWidget(remind_btn)
        layout.addLayout(btns)

    def _on_guide(self):
        if self._guide_url:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._guide_url))

    def _on_open(self):
        if self._url:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._url))

    def _on_skip(self):
        self.dismissed_for_version.emit(self._latest)
        self.close()


# === Radio source abstraction ===

class RadioSource:
    """Common interface for whatever produces baseband I/Q samples for the
    flowgraph — currently UHD's USRP source; SoapySDR-backed devices land
    in a sibling subclass. The main class doesn't talk to UHD directly any
    more; it talks through this interface so the wiring is swappable.

    Subclasses set `self.block` to the GR block emitting complex64 samples
    and implement the three set_* methods. `samp_rate_options` and
    `gain_range` let the UI adapt to the device's capabilities (subclasses
    override when the defaults — B210's range — aren't right)."""

    # The GR source block. Connected to the display chain at
    # dses_spectrum_analyzer.__init__'s "Connections" section.
    block = None

    # Discrete sample-rate choices the sidebar combo offers. Defaults to
    # FFT_SIZES-friendly rates that the B210 supports up to 25 MHz; Soapy
    # sources override with the device's actually-supported set.
    samp_rate_options = list(FFT_SIZES)  # placeholder; B210 overrides

    # (min_db, max_db, step_db) for the RX-gain slider in the sidebar.
    gain_range = (0.0, 76.0, 1.0)

    # Short label for the sidebar Device button and the window title.
    display_label = "(unknown radio)"

    # Verbose hardware description for SigMF metadata (core:hw field).
    hw_info = "(unknown radio)"

    # RF input ports the device exposes (e.g. ['TX/RX', 'RX2'] on a B210,
    # ['Tuner 1 50ohm', 'Tuner 2 50ohm'] on an RSPduo). Subclasses fill this
    # from the live block. A single-port radio leaves it length-1 (or empty)
    # and the sidebar omits the Antenna combo.
    antennas = []

    # The port currently selected; set by subclasses after opening.
    current_antenna = ""

    def set_samp_rate(self, hz: float) -> None:
        raise NotImplementedError

    def set_center_freq(self, hz: float) -> None:
        raise NotImplementedError

    def set_gain(self, db: float) -> None:
        raise NotImplementedError

    def set_antenna(self, name: str) -> None:
        # Default: radios with a single fixed port don't need to do anything.
        pass

    def antenna_needs_restart(self, name: str) -> bool:
        """True if applying antenna `name` changes the active RX frontend in a
        way that requires the flowgraph to be restarted (lock/unlock) for the
        change to take effect. Default: live setter is enough."""
        return False

    def samp_rate_range(self):
        """(min_hz, max_hz) the device will accept for a manual sample-rate
        entry. Default: the span of the discrete `samp_rate_options`; hardware-
        backed subclasses override with the device's real reported limits."""
        opts = self.samp_rate_options or [1e6]
        return (float(min(opts)), float(max(opts)))

    def get_actual_samp_rate(self) -> float:
        """The rate the device is really running, which can differ from the
        requested value after the driver snaps to an achievable rate. Return
        0.0 when unknown (the caller then keeps the requested value)."""
        return 0.0


class UhdB200Source(RadioSource):
    """Wraps `uhd.usrp_source` for B200-family devices (B200 / B210)."""

    # 0.625 and 1.25 MHz are the validated DSES lab simulator geometries
    # (UHF 625 kHz / L-band 1.25 MHz) — needed so a live .fil capture matches
    # the proven offline tsamp; the B210 supports rates well below 1 MHz.
    samp_rate_options = [0.625e6, 1e6, 1.25e6, 2e6, 4e6, 5e6, 8e6, 10e6,
                         16e6, 20e6, 25e6]
    gain_range = (0.0, 76.0, 1.0)

    def __init__(self, serial: str, samp_rate: float, center_freq: float,
                 gain: float, antenna: str = ""):
        self._serial = serial
        # Cache the live freq/gain so we can re-apply them after a receiver
        # (subdev) switch, which resets per-frontend state.
        self._cur_freq = center_freq
        self._cur_gain = gain
        self.block = uhd.usrp_source(
            ",".join((f'serial={serial}', '')),
            uhd.stream_args(
                cpu_format="fc32",
                args='recv_frame_size=8192,num_recv_frames=1024',
                channels=list(range(0, 1)),
            ),
        )
        self.block.set_samp_rate(samp_rate)
        self.block.set_time_unknown_pps(uhd.time_spec(0))
        self.block.set_center_freq(center_freq, 0)

        # The B210 has two RX frontends, mapped as subdevs "A:A" and "A:B"
        # (receiver A and receiver B). The B200 has just "A:A". The default
        # subdev spec lists all available frontends.
        try:
            self._subdevs = self.block.get_subdev_spec(0).split()
        except Exception:
            self._subdevs = []
        try:
            ports = list(self.block.get_antennas(0))   # e.g. ['TX/RX', 'RX2']
        except Exception:
            ports = []
        self._ports = ports
        self._recv_labels = ['A', 'B', 'C', 'D'][:len(self._subdevs)]
        if len(self._subdevs) >= 2 and ports:
            # Composite "<receiver> : <port>" — covers all physical inputs.
            self.antennas = [f"{r} : {p}"
                             for r in self._recv_labels for p in ports]
        else:
            # Single-receiver B200 (or unknown): plain port names.
            self.antennas = ports
        # The frontend the streamer is currently mapped to. Default mapping
        # for channel 0 is the first subdev (receiver A).
        self._current_subdev = self._subdevs[0] if self._subdevs else None

        chosen = self._pick_initial(antenna)
        self._apply(chosen)
        self.block.set_gain(gain, 0)
        self.display_label = f"USRP B210 — {serial}"
        self.hw_info = f"Ettus USRP B210 (s/n {serial})"

    def _pick_initial(self, saved: str) -> str:
        """Saved port if still valid; else prefer an RX2 input; else first."""
        if saved and saved in self.antennas:
            return saved
        for a in self.antennas:
            if a.endswith("RX2"):
                return a
        return self.antennas[0] if self.antennas else "RX2"

    def _split(self, name: str):
        """(subdev_spec_or_None, port) for a composite or plain antenna name."""
        if ' : ' in name:
            recv, port = name.split(' : ', 1)
            idx = self._recv_labels.index(recv) if recv in self._recv_labels else 0
            spec = self._subdevs[idx] if idx < len(self._subdevs) else None
            return spec, port
        return None, name

    def _apply(self, name: str) -> None:
        spec, port = self._split(name)
        if spec is not None and spec != self._current_subdev:
            # Remap channel 0 to a different RX frontend (receiver A↔B).
            # set_subdev_spec only takes effect when the RX streamer is
            # (re)created — the caller must do this while the flowgraph is
            # stopped or inside a lock()/unlock() cycle (see
            # antenna_needs_restart). Per-frontend params reset on the
            # remap, so re-apply freq + gain.
            self.block.set_subdev_spec(spec, 0)
            self.block.set_center_freq(self._cur_freq, 0)
            self.block.set_gain(self._cur_gain, 0)
            self._current_subdev = spec
        self.block.set_antenna(port, 0)
        self.current_antenna = name

    def antenna_needs_restart(self, name: str) -> bool:
        spec, _ = self._split(name)
        return spec is not None and spec != self._current_subdev

    def set_samp_rate(self, hz: float) -> None:
        # UHD snaps to the nearest achievable rate internally; read the result
        # back with get_actual_samp_rate().
        self.block.set_samp_rate(hz)

    def set_center_freq(self, hz: float) -> None:
        self._cur_freq = hz
        self.block.set_center_freq(hz, 0)

    def set_gain(self, db: float) -> None:
        self._cur_gain = db
        self.block.set_gain(db, 0)

    def set_antenna(self, name: str) -> None:
        self._apply(name)

    def samp_rate_range(self):
        """B210's real, master-clock-derived rate limits, from UHD."""
        try:
            r = self.block.get_samp_rates()      # uhd.meta_range_t
            lo, hi = float(r.start()), float(r.stop())
            if hi > lo > 0:
                return (lo, hi)
        except Exception:
            pass
        return RadioSource.samp_rate_range(self)

    def get_actual_samp_rate(self) -> float:
        try:
            return float(self.block.get_samp_rate())
        except Exception:
            return 0.0


# Per-Soapy-driver default sample-rate lists and gain ranges. SDRPlay
# devices share the same set; RTL-SDR is fixed at 2.4 MHz or 2.048 MHz
# in practice; HackRF can do up to 20 MHz; Airspy two rates; etc.
# These are used as the sidebar combo's options when the running source
# is the matching driver. If the device reports a different range via
# get_sample_rate_range(), the actual values are clamped at use time.
SOAPY_DEFAULTS = {
    # SDRPlay RSPx supports a set of discrete rates up to ~10 MHz.
    # SoapySDRPlay3's overall set_gain accepts 0..48 dB but it's actually
    # *gain reduction* — 0 = max gain, 48 = max attenuation. We invert at
    # the wrapper layer so the slider behaves like every other gain knob:
    # higher number = stronger signal.
    'sdrplay':  {
        'samp_rates': [2e6, 3e6, 4e6, 5e6, 6e6, 7e6, 8e6, 9e6, 10e6],
        'gain':      (0.0, 48.0, 1.0),
        'product':   "SDRPlay",
        'invert_gain': True,
    },
    'rtlsdr':   {
        'samp_rates': [0.25e6, 1.024e6, 1.4e6, 1.8e6, 1.92e6,
                       2.048e6, 2.4e6, 2.56e6, 2.8e6, 3.2e6],
        'gain':      (0.0, 49.6, 1.0),
        'product':   "RTL-SDR",
    },
    'hackrf':   {
        'samp_rates': [2e6, 4e6, 8e6, 10e6, 12.5e6, 16e6, 20e6],
        'gain':      (0.0, 47.0, 1.0),   # combined LNA + VGA approximation
        'product':   "HackRF",
    },
    'airspy':   {
        'samp_rates': [2.5e6, 10e6],
        'gain':      (0.0, 21.0, 1.0),
        'product':   "Airspy",
    },
    'airspyhf': {
        'samp_rates': [0.192e6, 0.256e6, 0.384e6, 0.768e6, 0.912e6],
        'gain':      (0.0, 48.0, 1.0),
        'product':   "Airspy HF+",
    },
    'bladerf':  {
        'samp_rates': [1e6, 2e6, 4e6, 8e6, 10e6, 16e6, 20e6, 25e6, 30e6, 40e6],
        'gain':      (0.0, 60.0, 1.0),
        'product':   "BladeRF",
    },
    'lime':     {
        'samp_rates': [2e6, 4e6, 5e6, 10e6, 15e6, 20e6, 30e6, 40e6],
        'gain':      (0.0, 70.0, 1.0),
        'product':   "LimeSDR",
    },
    'plutosdr': {
        'samp_rates': [0.6e6, 1e6, 2e6, 4e6, 5e6, 8e6, 10e6, 20e6, 30.72e6, 61.44e6],
        'gain':      (0.0, 73.0, 1.0),
        'product':   "PlutoSDR",
    },
}


class SoapyGenericSource(RadioSource):
    """Wraps gr-soapy's source block for any SoapySDR-recognised radio.
    Sample rate options and gain range come from SOAPY_DEFAULTS when the
    driver is known; otherwise we leave the defaults from the base class.
    The constructor signature mirrors UhdB200Source so the dispatch site
    in dses_spectrum_analyzer.__init__ stays uniform."""

    def __init__(self, driver: str, serial: str, samp_rate: float,
                 center_freq: float, gain: float, product: str = "",
                 antenna: str = ""):
        from gnuradio import soapy
        self._driver = driver
        self._serial = serial
        defaults = SOAPY_DEFAULTS.get(driver, {})
        self.samp_rate_options = list(defaults.get(
            'samp_rates', RadioSource.samp_rate_options))
        self.gain_range = defaults.get('gain', RadioSource.gain_range)
        # See SOAPY_DEFAULTS — some drivers (SDRplay) expose set_gain as
        # *gain reduction*, so we map the slider value through (max - x).
        self._invert_gain = bool(defaults.get('invert_gain', False))
        # Build the SoapySDR device-address string. driver= is required;
        # serial= disambiguates when multiple devices of the same driver
        # are attached.
        dev_args = f"driver={driver}"
        if serial:
            dev_args += f",serial={serial}"
        # gr-soapy source signature is positional:
        #   soapy.source(device, type, nchan, dev_args='', stream_args='',
        #                tune_args=[''], other_settings=[''])
        # We pass device-init args twice (once as device string, once in
        # dev_args) — the block accepts the redundancy.
        self.block = soapy.source(
            dev_args,                # SoapySDR device address
            "fc32",                  # complex64 output
            1,                       # 1 channel
            '',                      # dev_args (already in device string)
            '',                      # stream_args
            [''],                    # tune_args per channel
            [''],                    # other_settings per channel
        )
        # Clamp samp_rate to what the driver supports if known.
        if self.samp_rate_options and samp_rate not in self.samp_rate_options:
            # Pick the closest supported rate ≤ requested.
            below = [r for r in self.samp_rate_options if r <= samp_rate]
            samp_rate = max(below) if below else min(self.samp_rate_options)
        # Clamp gain to the driver's range.
        lo, hi, _ = self.gain_range
        gain = max(lo, min(hi, gain))
        self.block.set_sample_rate(0, samp_rate)
        self.block.set_frequency(0, center_freq)
        # Disable AGC so the user's gain slider actually takes effect.
        # SDRPlay drivers default to AGC=on and silently drop every set_gain
        # call ("Not updating IFGR gain because AGC is enabled") otherwise.
        # Not every driver supports the call; ignore if missing/unsupported.
        try:
            self.block.set_gain_mode(0, False)
        except Exception:
            pass
        # gr-soapy's set_gain(channel, value) takes overall gain in dB.
        # Some drivers (notably SDRPlay) expose multiple gain stages; the
        # overall setter applies the SoapySDR generic distribution.
        try:
            self.block.set_gain(0, self._driver_gain(float(gain)))
        except Exception as exc:
            # Some Soapy drivers fail on overall set_gain when only named
            # stages exist; don't kill the whole flow on a non-critical
            # setter failure.
            print(f"Soapy set_gain warning ({driver}): {exc}",
                  file=sys.stderr)

        # RF input ports this radio exposes (single-port radios report one,
        # e.g. RSP1B → ['RX']; the RSPduo reports its two tuners). Apply the
        # saved port if it's valid for this device.
        try:
            self.antennas = list(self.block.list_antennas(0))
        except Exception:
            self.antennas = []
        if antenna and antenna in self.antennas:
            try:
                self.block.set_antenna(0, antenna)
            except Exception as exc:
                print(f"Soapy set_antenna warning ({driver}): {exc}",
                      file=sys.stderr)
        try:
            self.current_antenna = self.block.get_antenna(0)
        except Exception:
            self.current_antenna = antenna or (
                self.antennas[0] if self.antennas else "")

        nice_name = product or defaults.get('product') or driver
        self.display_label = f"{nice_name} — {serial or '(no serial)'}"
        self.hw_info = (f"{nice_name} (s/n {serial})" if serial
                        else f"{nice_name} via SoapySDR ({driver})")

    def _driver_gain(self, slider_db: float) -> float:
        """Translate the user-facing gain value (higher = more signal) into
        whatever convention the underlying driver wants. For drivers flagged
        'invert_gain' (SDRPlay), the driver treats the number as *gain
        reduction*, so we send (max - slider). For everyone else we pass
        through unchanged."""
        if self._invert_gain:
            lo, hi, _ = self.gain_range
            return hi - (slider_db - lo)
        return slider_db

    def set_samp_rate(self, hz: float) -> None:
        # The UI clamps to samp_rate_range() (the driver's reported limits), so
        # pass the request straight through and let SoapySDR settle on the
        # nearest achievable rate; read it back with get_actual_samp_rate().
        # (Previously this snapped to the discrete preset list, which defeated
        # manual entry.)
        try:
            self.block.set_sample_rate(0, float(hz))
        except Exception as exc:
            print(f"Soapy set_sample_rate warning ({self._driver}): {exc}",
                  file=sys.stderr)

    def samp_rate_range(self):
        """The driver's reported sample-rate limits, via SoapySDR."""
        try:
            rngs = self.block.get_sample_rate_range(0)
            try:
                items = list(rngs)
            except TypeError:
                items = [rngs]
            mins, maxs = [], []
            for rg in items:
                mn = rg.minimum() if hasattr(rg, "minimum") else rg.start()
                mx = rg.maximum() if hasattr(rg, "maximum") else rg.stop()
                mins.append(float(mn))
                maxs.append(float(mx))
            if mins and maxs and max(maxs) > min(mins) > 0:
                return (min(mins), max(maxs))
        except Exception:
            pass
        return RadioSource.samp_rate_range(self)

    def get_actual_samp_rate(self) -> float:
        try:
            return float(self.block.get_sample_rate(0))
        except Exception:
            return 0.0

    def set_center_freq(self, hz: float) -> None:
        self.block.set_frequency(0, hz)

    def set_gain(self, db: float) -> None:
        lo, hi, _ = self.gain_range
        db = max(lo, min(hi, float(db)))
        try:
            self.block.set_gain(0, self._driver_gain(db))
        except Exception as exc:
            print(f"Soapy set_gain warning ({self._driver}): {exc}",
                  file=sys.stderr)

    def set_antenna(self, name: str) -> None:
        try:
            self.block.set_antenna(0, name)
            self.current_antenna = name
        except Exception as exc:
            print(f"Soapy set_antenna warning ({self._driver}): {exc}",
                  file=sys.stderr)


class dses_spectrum_analyzer(gr.top_block, QtWidgets.QWidget):

    # Both bases define `connect` and `disconnect`. PySide6's QObject.connect/
    # disconnect win MRO, so `self.(dis)connect((blk, 0), (blk2, 0))` ends up
    # at QObject and dies with "called with wrong argument types (tuple, tuple)".
    # Route through gr.top_block explicitly. Without the disconnect override,
    # _stop_recording would silently fail to remove the SigMF sink and the
    # file would keep growing until the program exits.
    def connect(self, *args, **kwargs):
        return gr.top_block.connect(self, *args, **kwargs)

    def disconnect(self, *args, **kwargs):
        return gr.top_block.disconnect(self, *args, **kwargs)

    def __init__(self):
        gr.top_block.__init__(self, f"{APP_NAME} v{APP_VERSION}", catch_exceptions=True)
        QtWidgets.QWidget.__init__(self)
        self.setWindowTitle(f"{APP_NAME}  —  v{APP_VERSION}")
        # Set the window/Dock icon to the bundled DSES pulsar on Windows/Linux.
        #
        # macOS is deliberately EXCLUDED: this process has BOTH Qt5 (pulled in
        # by GNU Radio's qtgui blocks) and Qt6 (PySide6) loaded, and setting a
        # raster icon there runs Qt6's setWindowIcon into Qt5's macOS bitmap
        # path (qt_mac_bitmapInfoForImage / QImage::format) and SIGSEGVs. The
        # old themed icon never crashed only because QIcon.fromTheme() is empty
        # on macOS. On macOS the Dock icon comes from the .app bundle's .icns
        # (install-shortcut.command) instead, so we simply skip it here.
        if sys.platform != 'darwin':
            try:
                icon_png = Path(__file__).resolve().parent / "icons" / "dses_sa.png"
                icon = (QtGui.QIcon(str(icon_png)) if icon_png.is_file()
                        else QtGui.QIcon.fromTheme('gnuradio-grc'))
                self.setWindowIcon(icon)
                app = QtWidgets.QApplication.instance()
                if app is not None and not icon.isNull():
                    app.setWindowIcon(icon)
            except BaseException as exc:
                print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)

        # Start stderr capture BEFORE the USRP source is built so we catch
        # any overflow indicators emitted during stream startup.
        self._overflow_monitor = OverflowMonitor(self)
        self._overflow_monitor.start()

        # INI-backed settings (created early so initial variable values can
        # come from it). Window geometry is also stored here, base64-encoded
        # in the [window] section (QSettings was unreliable on macOS).
        self._app_settings = Settings()
        # While True, control_changed handlers skip writes — used when
        # programmatically applying saved values back into the UI.
        self._applying_settings = False

        # Top-level vertical layout: menu bar above, plot+sidebar content below.
        top = QtWidgets.QVBoxLayout(self)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        top.setMenuBar(self._build_menu_bar())

        content = QtWidgets.QWidget()
        self.main_layout = QtWidgets.QHBoxLayout(content)
        self.main_layout.setContentsMargins(4, 4, 4, 4)
        self.main_layout.setSpacing(4)
        top.addWidget(content, 1)

        self.plots_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.plots_splitter.setChildrenCollapsible(False)
        self.main_layout.addWidget(self.plots_splitter, 1)

        self.sidebar = QtWidgets.QWidget()
        self.sidebar_layout = QtWidgets.QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        # Put the controls column inside a scroll area so a tall stack of
        # controls never forces the whole window taller than the display — it
        # scrolls instead. Without this, on a 14" MacBook Pro the sidebar's
        # natural height set a window minimum height larger than the screen,
        # so the window couldn't be dragged shorter.
        self._sidebar_scroll = QtWidgets.QScrollArea()
        self._sidebar_scroll.setWidget(self.sidebar)
        self._sidebar_scroll.setWidgetResizable(True)
        self._sidebar_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sidebar_scroll.setVerticalScrollBarPolicy(_VBAR_POLICY)
        self._sidebar_scroll.verticalScrollBar().setStyleSheet(_SCROLLBAR_QSS)
        self._sidebar_scroll.setMinimumWidth(290)
        self._sidebar_scroll.setMaximumWidth(380)   # ~360 content + scrollbar
        self._sidebar_scroll.setMinimumHeight(80)   # let the window shrink past it
        self.main_layout.addWidget(self._sidebar_scroll, 0)

        self._tuning_group = QtWidgets.QGroupBox("Tuning")
        self._tuning_group_layout = QtWidgets.QVBoxLayout(self._tuning_group)
        self.sidebar_layout.addWidget(self._tuning_group)

        self._rx_group = QtWidgets.QGroupBox("RX")
        self._rx_group_layout = QtWidgets.QVBoxLayout(self._rx_group)
        self.sidebar_layout.addWidget(self._rx_group)

        self._record_group = QtWidgets.QGroupBox("Recording")
        self._record_group_layout = QtWidgets.QVBoxLayout(self._record_group)
        self.sidebar_layout.addWidget(self._record_group)

        self._overflow_widget = OverflowDisplayWidget()
        self.sidebar_layout.addWidget(self._overflow_widget)
        self._overflow_monitor.chars_received.connect(self._overflow_widget.append_chars)

        self.sidebar_layout.addStretch(1)

        self.recording_dir = self._app_settings.get_str('recording', 'directory')
        if not self.recording_dir:
            self.recording_dir = str(Path.home() / "Documents" / "DSES_SA_Recordings")
        os.makedirs(self.recording_dir, exist_ok=True)

        # Recording format + .fil geometry (loaded from settings).
        fmt = self._app_settings.get_str('recording', 'format').strip().lower()
        self._record_format = fmt if fmt in ('iq', 'fil') else 'iq'
        self._fil_nchans = max(2, int(self._app_settings.get_int('recording', 'fil_nchans')))
        self._fil_integrate = max(1, int(self._app_settings.get_int('recording', 'fil_integrate')))
        self._fil_sink = None  # current FilterbankSink, or None when not recording

        self._recording_dir_button = QtWidgets.QPushButton("Folder: " + self._elided_dir())
        self._recording_dir_button.setToolTip(self.recording_dir)
        self._recording_dir_button.clicked.connect(self._on_change_recording_dir)
        self._record_group_layout.addWidget(self._recording_dir_button)

        # Default size; the saved size/position is applied later in showEvent,
        # once every widget exists (applying it here, mid-construction, gets
        # overwritten when the plots/controls are added afterward).
        self.resize(1280, 780)
        self._geometry_applied = False
        self.flowgraph_started = threading.Event()

        ##################################################
        # Variables (loaded from settings, fall back to DEFAULTS)
        ##################################################
        s = self._app_settings
        self.freq_preset    = freq_preset    = s.get_float('tuning', 'preset_hz')
        self.freq_offset_0  = freq_offset_0  = s.get_float('tuning', 'coarse_hz')
        self.freq_offset    = freq_offset    = s.get_float('tuning', 'fine_hz')
        self.freq_manual    = freq_manual    = s.get_float('tuning', 'manual_hz')
        self.samp_rate      = samp_rate      = s.get_float('rx', 'samp_rate_hz')
        self.gain           = gain           = s.get_float('rx', 'gain_db')
        saved_antenna       = s.get_str('rx', 'antenna')
        # `record` is intentionally NOT persisted — always start stopped.
        self.record         = 0
        self.center_freq    = center_freq    = ((freq_manual if freq_preset == 0 else freq_preset)
                                                + freq_offset + freq_offset_0)

        ##################################################
        # Blocks
        ##################################################

        # --- Resolve data source FIRST so the sample-rate combo + gain
        # slider built below can pull their options from the source's
        # capabilities (SDRPlay caps at 10 MHz; B210 goes to 25 MHz; etc.).
        chosen = resolve_device(
            self._app_settings.get_str('rx', 'device_driver'),
            self._app_settings.get_str('rx', 'device_serial'),
            parent=self)
        if not chosen:
            raise SystemExit(0)
        self._playback_mode = (chosen == PLAYBACK_SENTINEL)
        self._playback_path = None
        # In live mode: RadioSource wrapper around the actual radio block.
        # In playback mode: None (the file_source + throttle live in their
        # own attributes).
        self._source: 'RadioSource | None' = None
        # Backwards-compat alias used by _start_recording / _stop_recording
        # and the live-only setter guards. Kept as None in playback mode.
        self.uhd_usrp_source_0 = None

        if self._playback_mode:
            # Sample rate and center frequency come from the file's metadata,
            # not from the saved settings. Override the locals + self vars
            # before any widget construction that uses them.
            self._playback_path = find_default_sample_path()
            assert self._playback_path is not None
            pb_sr, pb_cf, _dtype = load_sigmf_meta(self._playback_path)
            self._playback_center_freq = pb_cf
            self.samp_rate = samp_rate = pb_sr
            self.center_freq = center_freq = pb_cf
            self._device_serial = None
            self._device_driver = None
            self._file_source = blocks.file_source(
                gr.sizeof_gr_complex,
                self._playback_path + '.sigmf-data',
                repeat=True)
            self._throttle = blocks.throttle(gr.sizeof_gr_complex, samp_rate, True)
            self._rotator = blocks.rotator_cc(0.0)
            # No RadioSource for playback; the sidebar uses a single-item
            # rate combo and a disabled gain slider (handled below).
            sr_options = [pb_sr]
            gain_range_tuple = (0.0, 76.0, 1.0)
            device_label_text = f"Playback: {Path(self._playback_path).name}.sigmf-data"
        else:
            assert isinstance(chosen, dict)
            self._device_driver = chosen['driver']
            self._device_serial = chosen['serial']
            self._save_setting('rx', 'device_driver', self._device_driver)
            self._save_setting('rx', 'device_serial', self._device_serial)
            try:
                if self._device_driver == DRIVER_UHD_B200:
                    src: RadioSource = UhdB200Source(
                        serial=chosen['serial'], samp_rate=samp_rate,
                        center_freq=center_freq, gain=gain,
                        antenna=saved_antenna)
                else:
                    src = SoapyGenericSource(
                        driver=self._device_driver,
                        serial=chosen['serial'],
                        samp_rate=samp_rate,
                        center_freq=center_freq,
                        gain=gain,
                        product=chosen.get('product', ''),
                        antenna=saved_antenna)
                    # Snap requested rate to the driver's nearest supported.
                    if src.samp_rate_options:
                        samp_rate = min(
                            src.samp_rate_options,
                            key=lambda r: abs(r - samp_rate))
                        self.samp_rate = samp_rate
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self, "Radio failed to open",
                    f"Could not open {chosen['label']}:\n\n"
                    f"{type(exc).__name__}: {exc}")
                raise SystemExit(0)
            self._source = src
            self.uhd_usrp_source_0 = src.block
            sr_options = list(src.samp_rate_options)
            gain_range_tuple = src.gain_range
            device_label_text = f"Device: {src.display_label}"

        # Window title shows the active radio so the user can see at a
        # glance which device is feeding the display.
        if self._playback_mode:
            assert self._playback_path is not None
            title_device = f"Playback: {Path(self._playback_path).name}"
        else:
            assert self._source is not None
            title_device = self._source.display_label
        self.setWindowTitle(f"{APP_NAME}  —  v{APP_VERSION}  —  {title_device}")

        # --- Sample-rate selector: device-aware presets + manual entry ---
        # The combo offers validated quick-pick rates; the Manual Rate box (like
        # Manual Frequency) accepts any rate the SDR supports, clamped to the
        # device's reported range and snapped by the driver to the nearest
        # achievable. Real-pulsar geometries that aren't presets go here.
        self._samp_rate_options = sr_options
        self._samp_rate_labels = [_pretty_rate(r) for r in sr_options]
        self._samp_rate_tool_bar = QtWidgets.QToolBar(self)
        self._samp_rate_tool_bar.addWidget(QtWidgets.QLabel("Sample Rate: "))
        self._samp_rate_combo_box = QtWidgets.QComboBox()
        self._samp_rate_tool_bar.addWidget(self._samp_rate_combo_box)
        for _label in self._samp_rate_labels:
            self._samp_rate_combo_box.addItem(_label)
        self._samp_rate_combo_box.currentIndexChanged.connect(
            self._on_samp_rate_combo)
        self._rx_group_layout.addWidget(self._samp_rate_tool_bar)

        self._samp_rate_manual_tool_bar = QtWidgets.QToolBar(self)
        self._samp_rate_manual_tool_bar.addWidget(
            QtWidgets.QLabel("Manual Rate (Hz): "))
        self._samp_rate_manual_line_edit = QtWidgets.QLineEdit()
        self._samp_rate_manual_tool_bar.addWidget(self._samp_rate_manual_line_edit)
        self._samp_rate_manual_line_edit.editingFinished.connect(
            self._on_samp_rate_manual_edit)
        self._rx_group_layout.addWidget(self._samp_rate_manual_tool_bar)
        # Populate the manual box + combo selection from the opening rate, and
        # show the device's real limits as a tooltip.
        self._refresh_samp_rate_limits_tooltip()
        self._sync_samp_rate_widgets()

        # --- Format selector: raw I/Q (SigMF) vs live filterbank (.fil) ---
        self._record_format_options = ['iq', 'fil']
        self._record_format_labels = ['Raw I/Q (SigMF)', 'Filterbank (.fil)']
        self._record_format_tool_bar = QtWidgets.QToolBar(self)
        self._record_format_tool_bar.addWidget(QtWidgets.QLabel("Format: "))
        self._record_format_combo = QtWidgets.QComboBox()
        for _label in self._record_format_labels:
            self._record_format_combo.addItem(_label)
        self._record_format_combo.setCurrentIndex(
            self._record_format_options.index(self._record_format))
        self._record_format_combo.setToolTip(
            "Raw I/Q: full-rate complex samples to a SigMF pair (large).\n"
            "Filterbank: channelize live and write a SIGPROC .fil directly "
            "(telescope_id 12) — the raw I/Q is never stored.")
        self._record_format_combo.currentIndexChanged.connect(
            lambda i: self.set_record_format(self._record_format_options[i]))
        self._record_format_tool_bar.addWidget(self._record_format_combo)
        self._record_group_layout.addWidget(self._record_format_tool_bar)

        # --- .fil geometry (only meaningful in filterbank mode) ---
        # A plain two-row grid, NOT a QToolBar. A QToolBar collapses any widget
        # that doesn't fit the available width into an overflow ("»") menu, and
        # in the narrow sidebar — especially once its vertical scrollbar appears
        # and steals ~17px — the Integrate spin box would drop into that overflow
        # and look like a blank field (Windows). A grid stacks the two labelled
        # rows and always shows both spin boxes regardless of sidebar width.
        self._fil_geom_widget = QtWidgets.QWidget(self)
        _fil_geom_grid = QtWidgets.QGridLayout(self._fil_geom_widget)
        _fil_geom_grid.setContentsMargins(0, 0, 0, 0)
        _fil_geom_grid.addWidget(QtWidgets.QLabel("Channels:"), 0, 0)
        self._fil_nchans_spin = _make_int_spinbox(
            2, 65536, self._fil_nchans,
            "Filterbank channel count (FFT size). tsamp = nchans*integrate/samp_rate.")
        self._fil_nchans_spin.valueChanged.connect(self.set_fil_nchans)
        _fil_geom_grid.addWidget(self._fil_nchans_spin, 0, 1)
        _fil_geom_grid.addWidget(QtWidgets.QLabel("Integrate:"), 1, 0)
        self._fil_integrate_spin = _make_int_spinbox(
            1, 65536, self._fil_integrate,
            "Power frames summed per output sample (1 = no integration).")
        self._fil_integrate_spin.valueChanged.connect(self.set_fil_integrate)
        _fil_geom_grid.addWidget(self._fil_integrate_spin, 1, 1)
        self._record_group_layout.addWidget(self._fil_geom_widget)

        # --- Record selector ---
        self._record_options = [0, 1]
        self._record_labels = ['Stopped', 'Recording']
        self._record_tool_bar = QtWidgets.QToolBar(self)
        self._record_tool_bar.addWidget(QtWidgets.QLabel("Record: "))
        self._record_combo_box = QtWidgets.QComboBox()
        self._record_tool_bar.addWidget(self._record_combo_box)
        for _label in self._record_labels:
            self._record_combo_box.addItem(_label)
        self._record_callback = lambda i: QtCore.QMetaObject.invokeMethod(
            self._record_combo_box, "setCurrentIndex",
            QtCore.Q_ARG("int", self._record_options.index(i)))
        self._record_callback(self.record)
        self._record_combo_box.currentIndexChanged.connect(
            lambda i: self.set_record(self._record_options[i]))
        self._record_group_layout.addWidget(self._record_tool_bar)

        # Status label below the Record combo, updated by _start/_stop_recording.
        self._recording_status = QtWidgets.QLabel("Idle")
        self._recording_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._recording_status.setWordWrap(True)
        self._record_group_layout.addWidget(self._recording_status)

        # Grey out the .fil geometry row unless filterbank format is selected.
        self._update_fil_geom_enabled()

        # --- Gain slider (device-aware range) ---
        gmin, gmax, gstep = gain_range_tuple
        clamped_gain = max(gmin, min(gmax, self.gain))
        if clamped_gain != self.gain:
            self.gain = clamped_gain  # device range is narrower than saved value
        self._gain_range = Range(gmin, gmax, gstep, clamped_gain, 200)
        self._gain_win = RangeWidget(self._gain_range, self.set_gain, "RX Gain (dB)",
                                      "counter_slider", float, Qt.Horizontal)
        self._rx_group_layout.addWidget(self._gain_win)

        # --- Antenna / RF-input selector (only when the radio has >1 port) ---
        # B210: TX/RX vs RX2. RSPduo: tuner 1 vs 2. RSPdx: antenna A/B/C.
        # Single-port radios (RSP1B → ['RX'], most RTL dongles) omit it.
        self._antenna_options = []
        if not self._playback_mode and self._source is not None:
            self._antenna_options = list(self._source.antennas)
        if len(self._antenna_options) > 1 and self._source is not None:
            self._antenna_tool_bar = QtWidgets.QToolBar(self)
            self._antenna_tool_bar.addWidget(QtWidgets.QLabel("Antenna: "))
            self._antenna_combo_box = QtWidgets.QComboBox()
            self._antenna_tool_bar.addWidget(self._antenna_combo_box)
            for _name in self._antenna_options:
                self._antenna_combo_box.addItem(_name)
            cur = self._source.current_antenna
            if cur in self._antenna_options:
                self._antenna_combo_box.setCurrentIndex(
                    self._antenna_options.index(cur))
            self._antenna_combo_box.currentIndexChanged.connect(
                lambda i: self.set_antenna(self._antenna_options[i]))
            self._rx_group_layout.addWidget(self._antenna_tool_bar)

        # --- Device picker button (label already computed above) ---
        self._device_button = QtWidgets.QPushButton(device_label_text)
        self._device_button.setToolTip(
            "Click to pick a different attached radio (when more than one is connected).")
        self._device_button.clicked.connect(self._on_change_device_clicked)
        if self._playback_mode:
            self._device_button.setEnabled(False)
        self._rx_group_layout.addWidget(self._device_button)

        # --- Spectrum display (replaces qtgui freq_sink + waterfall_sink) ---
        # Decimate aggressively before the Python sink: at 20 MS/s a pure-Python
        # sync_block can't keep up sample-by-sample. stream_to_vector groups
        # samples into CHUNK_SIZE-sized vectors and keep_one_in_n drops most
        # of them, so the sink sees ~20 vectors/sec.
        self._sample_sink = SampleBufferSink(chunk_size=CHUNK_SIZE)
        self._stream_to_vec = blocks.stream_to_vector(gr.sizeof_gr_complex, CHUNK_SIZE)
        self._keep_one_in_n = blocks.keep_one_in_n(
            gr.sizeof_gr_complex * CHUNK_SIZE,
            self._decim_for(samp_rate))
        self._fft_plot = FftPlotWidget(center_freq, samp_rate)
        self._fft_plot.set_y_axis(-140, 10)
        self._fft_plot.set_frequency_range(center_freq, samp_rate)
        self._waterfall_plot = WaterfallPlotWidget(center_freq, samp_rate, rows=256)
        self._waterfall_plot.set_intensity_range(-140, 10)

        self._processor = SpectrumProcessor(
            self._sample_sink, fft_size=1024, window_name="blackman-harris",
            update_hz=10.0, parent=self)
        self._processor.frame_ready.connect(self._fft_plot.on_frame)
        self._processor.frame_ready.connect(self._waterfall_plot.on_frame)
        self._fft_plot.request_fft_size.connect(self._processor.set_fft_size)
        self._fft_plot.request_window.connect(self._processor.set_window)
        self._fft_plot.request_average.connect(self._processor.set_average_alpha)
        self._fft_plot.request_max_hold.connect(self._processor.set_max_hold)
        self._fft_plot.request_min_hold.connect(self._processor.set_min_hold)
        self._fft_plot.request_reset_max.connect(self._processor.reset_max_hold)
        self._fft_plot.request_reset_min.connect(self._processor.reset_min_hold)
        self._fft_plot.request_window_normalized.connect(self._processor.set_window_normalized)

        # Keep the two control panels' visibility in lock-step so the spectrum
        # and waterfall plot regions stay equal-width. setChecked is a no-op
        # when the state already matches, so this can't recurse.
        self._fft_plot._toggle_btn.toggled.connect(self._waterfall_plot._toggle_btn.setChecked)
        self._waterfall_plot._toggle_btn.toggled.connect(self._fft_plot._toggle_btn.setChecked)
        # Persist panel visibility (single shared value since they're linked).
        self._fft_plot._toggle_btn.toggled.connect(
            lambda on: self._save_setting('ui', 'control_panels_visible', on))

        # Per-plot setting persistence. Each widget emits control_changed
        # (settings_key, value); we route to the appropriate INI section.
        self._fft_plot.control_changed.connect(
            lambda k, v: self._save_setting('spectrum', k, v))
        self._waterfall_plot.control_changed.connect(
            lambda k, v: self._save_setting('waterfall', k, v))

        self.plots_splitter.addWidget(self._fft_plot)
        self.plots_splitter.addWidget(self._waterfall_plot)
        self.plots_splitter.setStretchFactor(0, 1)
        self.plots_splitter.setStretchFactor(1, 1)
        self.plots_splitter.setSizes([400, 400])

        # --- Frequency preset radio group ---
        self._freq_preset_options = [408000000.0, 680500000.0, 1299500000.0,
                                     1422000000.0, 1666000000.0, 2304000000.0, 0]
        self._freq_preset_labels = ['408 MHz', '680.5 MHz', '1299.5 MHz',
                                    '1422 MHz (HI)', '1666 MHz (OH)', '2304 MHz', 'Manual']
        self._freq_preset_group_box = QtWidgets.QGroupBox("Pulsar Band: ")
        self._freq_preset_box = QtWidgets.QVBoxLayout()
        class variable_chooser_button_group(QtWidgets.QButtonGroup):
            def __init__(self, parent=None):
                QtWidgets.QButtonGroup.__init__(self, parent)
            @Slot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._freq_preset_button_group = variable_chooser_button_group()
        self._freq_preset_group_box.setLayout(self._freq_preset_box)
        for i, _label in enumerate(self._freq_preset_labels):
            radio_button = QtWidgets.QRadioButton(_label)
            self._freq_preset_box.addWidget(radio_button)
            self._freq_preset_button_group.addButton(radio_button, i)
        self._freq_preset_callback = lambda i: QtCore.QMetaObject.invokeMethod(
            self._freq_preset_button_group, "updateButtonChecked",
            QtCore.Q_ARG("int", self._freq_preset_options.index(i)))
        self._freq_preset_callback(self.freq_preset)
        # PySide6 / Qt6: use idClicked instead of PyQt5's buttonClicked[int]
        self._freq_preset_button_group.idClicked.connect(
            lambda i: self.set_freq_preset(self._freq_preset_options[i]))
        self._tuning_group_layout.addWidget(self._freq_preset_group_box)

        self._freq_offset_0_range = Range(-100e6, 100e6, 100e3, self.freq_offset_0, 200)
        self._freq_offset_0_win = RangeWidget(self._freq_offset_0_range, self.set_freq_offset_0,
                                               "Coarse Tune (Hz)", "counter_slider",
                                               float, Qt.Horizontal)
        self._tuning_group_layout.addWidget(self._freq_offset_0_win)

        self._freq_offset_range = Range(-10e6, 10e6, 100e3, self.freq_offset, 200)
        self._freq_offset_win = RangeWidget(self._freq_offset_range, self.set_freq_offset,
                                             "Fine Tune (Hz)", "counter_slider",
                                             float, Qt.Horizontal)
        self._tuning_group_layout.addWidget(self._freq_offset_win)

        self._freq_manual_tool_bar = QtWidgets.QToolBar(self)
        self._freq_manual_tool_bar.addWidget(QtWidgets.QLabel("Manual Frequency (Hz): "))
        self._freq_manual_line_edit = QtWidgets.QLineEdit(str(self.freq_manual))
        self._freq_manual_tool_bar.addWidget(self._freq_manual_line_edit)
        self._freq_manual_line_edit.editingFinished.connect(
            lambda: self.set_freq_manual(eng_notation.str_to_num(str(self._freq_manual_line_edit.text()))))
        self._tuning_group_layout.addWidget(self._freq_manual_tool_bar)

        # --- Recording: SigMF sink is built on demand in _start_recording()
        # and torn down in _stop_recording() via top_block.lock()/unlock().
        # The previous always-on valve+sink combo wrote to disk from launch
        # and the valve toggle didn't actually gate in real time — that was
        # the source of the freeze when Record was clicked at high sample
        # rates (the valve toggle contended with the always-busy sink). ---
        self._sigmf_sink = None  # current sink, or None when not recording

        ##################################################
        # Connections
        ##################################################
        # Display branch: source -> chunk -> decimate -> Python sink. The
        # source differs between live (USRP) and playback (file → throttle →
        # rotator for digital retuning).
        if self._playback_mode:
            self.connect((self._file_source, 0), (self._throttle, 0))
            self.connect((self._throttle, 0), (self._rotator, 0))
            self.connect((self._rotator, 0), (self._stream_to_vec, 0))
        else:
            self.connect((self.uhd_usrp_source_0, 0), (self._stream_to_vec, 0))
        self.connect((self._stream_to_vec, 0), (self._keep_one_in_n, 0))
        self.connect((self._keep_one_in_n, 0), (self._sample_sink, 0))

        # Push the saved spectrum + waterfall + UI settings into the widgets
        # now that everything exists. Top-level values (tuning, gain, samp,
        # recording dir) were applied above via the variable initialisation.
        self._apply_widget_settings()

        # In playback mode, disable everything that depends on a real USRP.
        if self._playback_mode:
            self._apply_playback_ui()

        # Set up the auto-update checker (background thread, fires the
        # update-available signal if the configured manifest URL advertises
        # a newer version). Configured URL = no traffic until the developer
        # publishes one.
        self._setup_update_checker()

    @staticmethod
    def _decim_for(samp_rate, target_vec_per_sec=20):
        """Pick keep_one_in_n's N so the Python sink sees ~target vectors/sec."""
        return max(1, int(round(samp_rate / CHUNK_SIZE / float(target_vec_per_sec))))

    def _apply_playback_ui(self):
        """Disable the controls that have no meaning for a recorded file
        (sample rate, gain, recording) and label the recording status. The
        Tuning group stays enabled — it drives a digital frequency shift
        within the recording's bandwidth via blocks.rotator_cc."""
        self.setWindowTitle(f"{APP_NAME}  —  v{APP_VERSION}  [Playback]")
        self._tuning_group.setToolTip(
            "Virtual tuning: shifts the spectrum digitally within the "
            "recording's bandwidth. Outside ±(samp_rate/2) of the file's "
            "original center frequency you'll just see noise / wrap-around.")
        self._samp_rate_tool_bar.setEnabled(False)
        self._samp_rate_tool_bar.setToolTip("Disabled in playback mode "
                                             "(sample rate comes from the file).")
        self._samp_rate_manual_tool_bar.setEnabled(False)
        self._samp_rate_manual_tool_bar.setToolTip(
            "Disabled in playback mode (sample rate comes from the file).")
        self._gain_win.setEnabled(False)
        self._gain_win.setToolTip("Disabled in playback mode.")
        self._record_tool_bar.setEnabled(False)
        self._record_tool_bar.setToolTip("Recording is disabled in playback mode.")
        self._record_format_tool_bar.setEnabled(False)
        self._fil_geom_widget.setEnabled(False)
        self._recording_dir_button.setEnabled(False)
        if self._playback_path:
            self._recording_status.setText(
                f"Playback (looping): {Path(self._playback_path).name}.sigmf-data")
            self._recording_status.setToolTip(self._playback_path + '.sigmf-data')

    def _build_menu_bar(self):
        bar = QtWidgets.QMenuBar(self)
        help_menu = bar.addMenu("&Help")
        guide_act = QtGui.QAction("&User Guide", self)
        guide_act.setShortcut(QtGui.QKeySequence.HelpContents)
        guide_act.triggered.connect(self._show_help_dialog)
        help_menu.addAction(guide_act)
        update_act = QtGui.QAction("Check for &Updates…", self)
        update_act.triggered.connect(self._check_for_updates_manual)
        help_menu.addAction(update_act)
        about_act = QtGui.QAction("&About…", self)
        about_act.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_act)
        return bar

    def _show_help_dialog(self):
        HelpDialog(self).exec()

    def _show_about_dialog(self):
        dlg = AboutDialog(self._app_settings, self)
        dlg.defaults_requested.connect(self._on_defaults_requested)
        dlg.exec()

    # --- auto-update plumbing ---

    def _setup_update_checker(self):
        """Create the checker, wire its signals to the notification dialog,
        and kick off a background check if auto-check is on AND we haven't
        checked recently AND a manifest URL is configured."""
        s = self._app_settings
        self._update_checker = UpdateChecker(s, parent=self)
        self._update_checker.update_available.connect(self._show_update_dialog)
        # Don't bother the user with no_update / check_failed on the auto path —
        # those are connected only for the manual menu trigger via _check_for_updates_manual.
        if not s.get_bool('updates', 'auto_check'):
            return
        if not s.get_str('updates', 'manifest_url').strip():
            return  # no URL configured yet
        # Debounce
        last_iso = s.get_str('updates', 'last_check_iso')
        try:
            interval_h = max(1, s.get_int('updates', 'check_interval_hours'))
        except Exception:
            interval_h = 24
        if last_iso:
            try:
                last = datetime.fromisoformat(last_iso)
                if (datetime.now() - last).total_seconds() < interval_h * 3600:
                    return  # checked recently, skip
            except ValueError:
                pass
        # Trigger after the GUI has painted at least once so the dialog
        # doesn't appear before the main window.
        QTimer.singleShot(2000, self._update_checker.check_now)

    @Slot(str, str, str)
    def _show_update_dialog(self, latest, url, notes):
        # Respect a previously-clicked "Skip this version" — don't re-show
        # the dialog unless the manifest now advertises a strictly newer one.
        dismissed = self._app_settings.get_str('updates', 'dismissed_version').strip()
        if dismissed and _parse_version(latest) <= _parse_version(dismissed):
            return
        dlg = UpdateNotificationDialog(latest, url, notes, APP_VERSION, parent=self)
        dlg.dismissed_for_version.connect(self._on_update_dismissed)
        dlg.show()  # non-modal
        # Keep a reference so it isn't garbage-collected when this slot returns.
        self._update_dialog = dlg

    @Slot(str)
    def _on_update_dismissed(self, version):
        self._app_settings.set('updates', 'dismissed_version', version)
        try:
            self._app_settings.save()
        except OSError:
            pass

    def _check_for_updates_manual(self):
        """Help → Check for Updates… handler. Wires the no_update /
        check_failed signals to a one-shot dialog for this invocation."""
        s = self._app_settings
        url = s.get_str('updates', 'manifest_url').strip()
        if not url:
            QtWidgets.QMessageBox.information(
                self, "Updates",
                "Auto-update is not configured: the '[updates] manifest_url' "
                "setting is empty.\n\nAsk the program's distributor for the "
                "manifest URL and add it to your settings.ini, or use "
                "Help → About → Open Settings Folder to find the file.")
            return
        # Make a one-off checker so its signals don't accumulate handlers.
        ck = UpdateChecker(s, parent=self)
        ck.update_available.connect(self._show_update_dialog)
        ck.no_update.connect(lambda v: QtWidgets.QMessageBox.information(
            self, "Updates",
            f"You're running the latest version ({APP_VERSION}).\n\n"
            f"Manifest reports latest = {v}."))
        ck.check_failed.connect(lambda msg: QtWidgets.QMessageBox.warning(
            self, "Update check failed",
            f"Could not reach the update server.\n\n{msg}"))
        ck.check_now()

    def _on_defaults_requested(self):
        """After 'Restore Defaults' rewrites the INI, push every saved value
        back through the widgets and the flowgraph."""
        s = self._app_settings
        # Tuning + RX + recording dir
        self.recording_dir = s.get_str('recording', 'directory')
        os.makedirs(self.recording_dir, exist_ok=True)
        self._recording_dir_button.setText("Folder: " + self._elided_dir())
        self._recording_dir_button.setToolTip(self.recording_dir)
        # set_* methods drive the flowgraph and re-save to settings, so guard
        # with _applying_settings to avoid redundant writes.
        self._applying_settings = True
        try:
            self.set_samp_rate(s.get_float('rx', 'samp_rate_hz'))
            self.set_gain(s.get_float('rx', 'gain_db'))
            self.set_freq_preset(s.get_float('tuning', 'preset_hz'))
            self.set_freq_offset_0(s.get_float('tuning', 'coarse_hz'))
            self.set_freq_offset(s.get_float('tuning', 'fine_hz'))
            self.set_freq_manual(s.get_float('tuning', 'manual_hz'))
        finally:
            self._applying_settings = False
        self._apply_widget_settings()

    def _apply_widget_settings(self):
        """Push spectrum/waterfall/UI settings into the plot widgets and
        propagate to the processor."""
        self._applying_settings = True
        try:
            self._fft_plot.apply_settings(self._app_settings)
            self._waterfall_plot.apply_settings(self._app_settings)
            panels_on = self._app_settings.get_bool('ui', 'control_panels_visible')
            self._fft_plot._toggle_btn.setChecked(panels_on)
            self._waterfall_plot._toggle_btn.setChecked(panels_on)
        finally:
            self._applying_settings = False
        # Push the values into the processor explicitly (signals were blocked
        # while we set the UI to avoid the save round-trip).
        self._fft_plot.emit_settings_to_processor()

    def _save_setting(self, section, key, value):
        if self._applying_settings:
            return
        self._app_settings.set(section, key, value)
        try:
            self._app_settings.save()
        except OSError as exc:
            print(f"Settings save failed: {exc}", file=sys.stderr)

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        # Apply the saved size/position once, on first show — after every
        # widget exists and the window is being realized, so the resize sticks
        # (doing it during __init__ gets overwritten as later widgets are added).
        if not self._geometry_applied:
            self._geometry_applied = True
            self._restore_geometry()
            self._clamp_window_to_screen()

    def _restore_geometry(self):
        """Apply the saved window position/size (plain ints in the INI)."""
        try:
            gw = self._app_settings.get_int('window', 'width')
            gh = self._app_settings.get_int('window', 'height')
            if gw > 0 and gh > 0:
                self.resize(gw, gh)
                self.move(self._app_settings.get_int('window', 'x'),
                          self._app_settings.get_int('window', 'y'))
        except Exception as exc:
            print(f"Geometry restore failed: {exc}", file=sys.stderr)

    def _clamp_window_to_screen(self):
        """Shrink and reposition the window so it fits entirely on its screen.
        Guards against a saved geometry (from a larger display or a pre-scroll
        layout) leaving the window taller/wider than this display — which the
        user can't fix by dragging once the title bar is above the screen top."""
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w = min(self.width(), avail.width())
        h = min(self.height(), avail.height())
        if w != self.width() or h != self.height():
            self.resize(w, h)
        # Nudge fully on-screen if a saved position pushed it partly off.
        x = max(avail.left(), min(self.x(), avail.right() - w + 1))
        y = max(avail.top(), min(self.y(), avail.bottom() - h + 1))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def _save_geometry(self):
        """Persist the window position/size into the INI as plain integers.
        Used by closeEvent and the signal handler. The INI saves reliably on
        every platform, unlike QSettings on macOS."""
        try:
            g = self.geometry()
            self._app_settings.set('window', 'x', int(g.x()))
            self._app_settings.set('window', 'y', int(g.y()))
            self._app_settings.set('window', 'width', int(g.width()))
            self._app_settings.set('window', 'height', int(g.height()))
            self._app_settings.save()
        except Exception as exc:
            print(f"Geometry save failed: {exc}", file=sys.stderr)

    def closeEvent(self, event):
        # Save window geometry + flush any tail-end setting edits to the INI.
        self._save_geometry()
        try:
            self._app_settings.save()
        except OSError as exc:
            print(f"Settings save on close failed: {exc}", file=sys.stderr)
        # Stop recording first (gracefully flush the SigMF file) before
        # tearing down the flowgraph.
        try:
            self._stop_recording()
        except Exception:
            pass
        # Restore the real stderr before GR shuts down so any shutdown logs
        # land on the console rather than a closed pipe.
        try:
            self._overflow_monitor.stop()
        except Exception:
            pass
        self.stop()
        self.wait()
        event.accept()

    def _elided_dir(self):
        d = self.recording_dir
        if len(d) > 32:
            return "..." + d[-29:]
        return d

    def _on_change_recording_dir(self):
        new_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose recording folder",
            self.recording_dir,
        )
        if not new_dir:
            return
        self.recording_dir = new_dir
        self._save_setting('recording', 'directory', new_dir)
        self._recording_dir_button.setText("Folder: " + self._elided_dir())
        self._recording_dir_button.setToolTip(new_dir)
        QtWidgets.QMessageBox.information(
            self,
            "Recording folder changed",
            "New folder will be used the next time the program is launched."
        )

    def _on_change_device_clicked(self):
        """Re-open the device picker. Switching to a different radio needs
        a full flowgraph rebuild, so for now we just save the choice and
        tell the user it'll take effect next launch."""
        devices = find_all_radios()
        if not devices:
            QtWidgets.QMessageBox.warning(
                self, "No radio found",
                "No supported SDR is currently attached. Plug one in and "
                "try again.")
            return
        dlg = DevicePickerDialog(
            devices, current_driver=self._device_driver,
            current_serial=self._device_serial, parent=self,
            prompt="Pick a radio for the next launch:")
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        new_dev = dlg.selected_device()
        if not new_dev:
            return
        if (new_dev['driver'] == self._device_driver
                and new_dev['serial'] == self._device_serial):
            return
        self._save_setting('rx', 'device_driver', new_dev['driver'])
        self._save_setting('rx', 'device_serial', new_dev['serial'])
        QtWidgets.QMessageBox.information(
            self, "Radio changed",
            f"Will use {new_dev['label']} on next launch.\n\n"
            f"(Hot-swap of the radio source is not supported yet — "
            f"close and re-open the program to apply.)")

    def get_freq_preset(self):
        return self.freq_preset

    def set_freq_preset(self, freq_preset):
        self.freq_preset = freq_preset
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)
        self._freq_preset_callback(self.freq_preset)
        self._save_setting('tuning', 'preset_hz', float(freq_preset))

    def get_freq_offset_0(self):
        return self.freq_offset_0

    def set_freq_offset_0(self, freq_offset_0):
        self.freq_offset_0 = freq_offset_0
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)
        self._save_setting('tuning', 'coarse_hz', float(freq_offset_0))

    def get_freq_offset(self):
        return self.freq_offset

    def set_freq_offset(self, freq_offset):
        self.freq_offset = freq_offset
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)
        self._save_setting('tuning', 'fine_hz', float(freq_offset))

    def get_freq_manual(self):
        return self.freq_manual

    def set_freq_manual(self, freq_manual):
        self.freq_manual = freq_manual
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)
        QtCore.QMetaObject.invokeMethod(self._freq_manual_line_edit, "setText",
                                        QtCore.Q_ARG("QString", eng_notation.num_to_str(self.freq_manual)))
        self._save_setting('tuning', 'manual_hz', float(freq_manual))

    def get_samp_rate(self):
        return self.samp_rate

    def _samp_rate_limits(self):
        """(min_hz, max_hz) the current SDR accepts; falls back to the combo
        span when there's no live source (e.g. playback)."""
        if self._source is not None:
            try:
                lo, hi = self._source.samp_rate_range()
                if hi > lo > 0:
                    return float(lo), float(hi)
            except Exception:
                pass
        opts = self._samp_rate_options or [self.samp_rate]
        return float(min(opts)), float(max(opts))

    def _refresh_samp_rate_limits_tooltip(self):
        lo, hi = self._samp_rate_limits()
        tip = (f"Any rate the SDR supports: {_pretty_rate(lo)} – "
               f"{_pretty_rate(hi)}.\nOut-of-range values are clamped; the "
               f"radio then snaps to the nearest rate it can deliver.")
        self._samp_rate_manual_line_edit.setToolTip(tip)
        self._samp_rate_manual_tool_bar.setToolTip(tip)

    def _sync_samp_rate_widgets(self):
        """Reflect the true current rate: the manual box always shows it, the
        combo selects a matching preset or clears (-1) for a custom rate.
        Signals are blocked so this never re-enters set_samp_rate."""
        with _SignalBlocker(self._samp_rate_manual_line_edit):
            self._samp_rate_manual_line_edit.setText(
                eng_notation.num_to_str(self.samp_rate))
        idx = -1
        for k, r in enumerate(self._samp_rate_options):
            if abs(r - self.samp_rate) <= max(1.0, r * 1e-6):
                idx = k
                break
        with _SignalBlocker(self._samp_rate_combo_box):
            self._samp_rate_combo_box.setCurrentIndex(idx)

    def _on_samp_rate_combo(self, i):
        if 0 <= i < len(self._samp_rate_options):
            self.set_samp_rate(self._samp_rate_options[i])

    def _on_samp_rate_manual_edit(self):
        txt = str(self._samp_rate_manual_line_edit.text())
        try:
            hz = eng_notation.str_to_num(txt)
        except Exception:
            self._sync_samp_rate_widgets()   # bad input -> revert to current
            return
        self.set_samp_rate(hz)

    def set_samp_rate(self, samp_rate):
        if self._playback_mode or self._source is None:
            return  # rate is fixed by the playback file
        lo, hi = self._samp_rate_limits()
        req = max(lo, min(hi, float(samp_rate)))
        self._source.set_samp_rate(req)
        # Trust the rate the radio actually settled on (drivers snap), so the
        # display, decimation, and .fil tsamp all reflect reality.
        actual = self._source.get_actual_samp_rate()
        self.samp_rate = float(actual) if actual and actual > 0 else req
        self._sync_samp_rate_widgets()
        self._fft_plot.set_frequency_range(self.center_freq, self.samp_rate)
        self._waterfall_plot.set_frequency_range(self.center_freq, self.samp_rate)
        self._keep_one_in_n.set_n(self._decim_for(self.samp_rate))
        self._save_setting('rx', 'samp_rate_hz', float(self.samp_rate))
        # Stale overflow indicators from the old rate aren't meaningful any
        # more, and there's usually a small burst during retuning.
        self._overflow_widget.clear()

    def get_record(self):
        return self.record

    def set_record(self, record):
        # Intentionally NOT persisted — always launch with recording stopped.
        new = int(record)
        if new == self.record:
            return
        self.record = new
        self._record_callback(self.record)
        if self.record:
            self._start_recording()
        else:
            self._stop_recording()

    def _update_fil_geom_enabled(self):
        """The .fil geometry row only applies in filterbank format, and must
        not change mid-recording."""
        editable = (self._record_format == 'fil') and not self.record
        self._fil_geom_widget.setEnabled(editable)

    def get_record_format(self):
        return self._record_format

    def set_record_format(self, fmt):
        """Switch between raw-I/Q (SigMF) and live-filterbank (.fil) recording.
        Disallowed mid-recording — stop first."""
        fmt = 'fil' if str(fmt).lower() == 'fil' else 'iq'
        if fmt == self._record_format:
            return
        if self.record:
            # Revert the combo to the active format; can't switch while live.
            QtWidgets.QMessageBox.information(
                self, "Stop recording first",
                "Stop the current recording before changing the format.")
            with _SignalBlocker(self._record_format_combo):
                self._record_format_combo.setCurrentIndex(
                    self._record_format_options.index(self._record_format))
            return
        self._record_format = fmt
        with _SignalBlocker(self._record_format_combo):
            self._record_format_combo.setCurrentIndex(
                self._record_format_options.index(fmt))
        self._save_setting('recording', 'format', fmt)
        self._update_fil_geom_enabled()

    def set_fil_nchans(self, n):
        self._fil_nchans = max(2, int(n))
        self._save_setting('recording', 'fil_nchans', self._fil_nchans)

    def set_fil_integrate(self, n):
        self._fil_integrate = max(1, int(n))
        self._save_setting('recording', 'fil_integrate', self._fil_integrate)

    def _start_recording(self):
        """Begin recording in the selected format. Filterbank (.fil) channelizes
        live and writes a SIGPROC file directly; raw I/Q goes to a SigMF pair."""
        if self._playback_mode or self.uhd_usrp_source_0 is None:
            return  # nothing real to record from
        self._update_fil_geom_enabled()  # lock geometry while live
        if self._record_format == 'fil':
            self._start_fil_recording()
        else:
            self._start_sigmf_recording()

    def _start_fil_recording(self):
        """Splice a live FilterbankSink into the running flowgraph: it
        channelizes the SDR stream and writes a SIGPROC .fil (telescope_id 12)
        straight to disk, using the shared sigproc_fil core."""
        if self._fil_sink is not None:
            return  # already recording
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.recording_dir,
                            f"DSES_Spectrum_Analyzer_{ts}.fil")
        try:
            sink = sigproc_fil.FilterbankSink(
                path, nchans=self._fil_nchans, samp_rate=self.samp_rate,
                center_freq_mhz=self.center_freq / 1e6,
                tstart_mjd=sigproc_fil.unix_to_mjd(time.time()),
                integrate=self._fil_integrate, source_name="capture")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Recording failed to start",
                f"Could not create filterbank writer:\n\n{exc}")
            self.record = 0
            self._record_callback(0)
            self._update_fil_geom_enabled()
            return
        try:
            self.lock()
            try:
                self.connect((self.uhd_usrp_source_0, 0), (sink, 0))
            finally:
                self.unlock()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Recording failed to start",
                f"Could not splice filterbank sink into flowgraph:\n\n{exc}")
            try:
                sink.close()
            except Exception:
                pass
            self.record = 0
            self._record_callback(0)
            self._update_fil_geom_enabled()
            return
        self._fil_sink = sink
        self._fil_sink_path = path
        tsamp_ms = self._fil_nchans * self._fil_integrate / self.samp_rate * 1e3
        self._recording_status.setText(
            f"Recording → {os.path.basename(path)} "
            f"({self._fil_nchans} ch, tsamp {tsamp_ms:.4g} ms)")
        self._recording_status.setToolTip(path)

    def _start_sigmf_recording(self):
        """Construct a fresh SigMF sink with a timestamped filename and
        splice it into the running flowgraph via top_block.lock()/unlock()."""
        if self._playback_mode or self.uhd_usrp_source_0 is None:
            return  # nothing real to record from
        if self._sigmf_sink is not None:
            return  # already recording
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self.recording_dir,
                            f"DSES_Spectrum_Analyzer_{ts}")
        try:
            assert self._source is not None  # guarded by _playback_mode check above
            sink = blocks.sigmf_sink_minimal(
                item_size=gr.sizeof_gr_complex,
                filename=base,
                sample_rate=self.samp_rate,
                center_freq=self.center_freq,
                author=APP_AUTHOR,
                description=f"Spectrum analyzer capture ({self._source.display_label})",
                hw_info=self._source.hw_info,
                is_complex=True)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Recording failed to start",
                f"Could not create SigMF sink:\n\n{exc}")
            # Roll the combo back to Stopped so the UI stays truthful.
            self.record = 0
            self._record_callback(0)
            return
        try:
            self.lock()
            try:
                self.connect((self.uhd_usrp_source_0, 0), (sink, 0))
            finally:
                self.unlock()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Recording failed to start",
                f"Could not splice SigMF sink into flowgraph:\n\n{exc}")
            self.record = 0
            self._record_callback(0)
            return
        self._sigmf_sink = sink
        self._sigmf_sink_path = base
        self._recording_status.setText(
            f"Recording → {os.path.basename(base)}.sigmf-data")
        self._recording_status.setToolTip(f"{base}.sigmf-data")

    def _stop_recording(self):
        """Pull whichever recording sink is active out of the flowgraph and
        finalize its file."""
        if self._fil_sink is not None:
            self._stop_fil_recording()
        else:
            self._stop_sigmf_recording()
        self._update_fil_geom_enabled()  # geometry editable again once stopped

    def _stop_fil_recording(self):
        """Disconnect the FilterbankSink and close it so the .fil is flushed."""
        sink = self._fil_sink
        if sink is None:
            return
        self._fil_sink = None
        try:
            self.lock()
            try:
                self.disconnect((self.uhd_usrp_source_0, 0), (sink, 0))
            finally:
                self.unlock()
        except Exception as exc:
            print(f"Recording disconnect failed: {exc}", file=sys.stderr)
        try:
            sink.close()  # flush + close the .fil
        except Exception as exc:
            print(f"Filterbank close failed: {exc}", file=sys.stderr)
        path = getattr(self, '_fil_sink_path', '')
        if path:
            self._recording_status.setText(f"Saved → {os.path.basename(path)}")
            self._recording_status.setToolTip(path)
        else:
            self._recording_status.setText("Idle")
            self._recording_status.setToolTip("")

    def _stop_sigmf_recording(self):
        """Pull the SigMF sink out of the flowgraph and drop the Python
        reference so its destructor finalizes the data file."""
        sink = self._sigmf_sink
        if sink is None:
            return
        self._sigmf_sink = None
        try:
            self.lock()
            try:
                self.disconnect((self.uhd_usrp_source_0, 0), (sink, 0))
            finally:
                self.unlock()
        except Exception as exc:
            print(f"Recording disconnect failed: {exc}", file=sys.stderr)
        del sink  # let GC run the destructor and flush the file
        path = getattr(self, '_sigmf_sink_path', '')
        if path:
            self._recording_status.setText(
                f"Saved → {os.path.basename(path)}.sigmf-data")
            self._recording_status.setToolTip(f"{path}.sigmf-data")
        else:
            self._recording_status.setText("Idle")
            self._recording_status.setToolTip("")

    def get_gain(self):
        return self.gain

    def set_gain(self, gain):
        if self._playback_mode or self._source is None:
            return  # no gain knob in playback mode
        self.gain = gain
        self._source.set_gain(self.gain)
        self._save_setting('rx', 'gain_db', float(gain))

    def set_antenna(self, name):
        if self._playback_mode or self._source is None:
            return  # no antenna selection in playback mode
        # A plain port change within a receiver (B210 TX/RX↔RX2) takes effect
        # live. Switching the active *receiver* (A↔B) remaps channel 0 to a
        # different RX frontend, which only takes hold when the source block's
        # RX streamer is created fresh — a runtime set_subdev_spec (even under
        # lock/unlock) does not rebind the live streamer. So we tear down and
        # rebuild the source block on a receiver change.
        if self._source.antenna_needs_restart(name):
            if self._sigmf_sink is not None or self._fil_sink is not None:
                QtWidgets.QMessageBox.information(
                    self, "Stop recording first",
                    "Switching between receiver A and receiver B restarts the "
                    "radio, which can't be done while recording. Stop the "
                    "recording, then switch receivers.")
                self._sync_antenna_combo()  # revert combo to the live port
                return
            self._rebuild_source_for_antenna(name)
        else:
            self._source.set_antenna(name)
        self._save_setting('rx', 'antenna', name)

    def _rebuild_source_for_antenna(self, name):
        """Tear the radio source out of the flowgraph and rebuild it on the
        requested antenna/receiver. Needed because the active RX frontend is
        fixed when the source's streamer is created; only a fresh block picks
        up a different receiver. Brief stream gap while it restarts."""
        import gc
        self.stop()
        self.wait()
        self.disconnect((self.uhd_usrp_source_0, 0), (self._stream_to_vec, 0))
        # Release the old device handle fully (the B210 is exclusive-access)
        # before opening it again on the new frontend.
        self._source = None
        self.uhd_usrp_source_0 = None
        gc.collect()
        assert self._device_serial is not None  # always set in live mode
        new = UhdB200Source(
            serial=self._device_serial, samp_rate=self.samp_rate,
            center_freq=self.center_freq, gain=self.gain, antenna=name)
        self._source = new
        self.uhd_usrp_source_0 = new.block
        self.connect((self.uhd_usrp_source_0, 0), (self._stream_to_vec, 0))
        self.start()
        self._overflow_widget.clear()

    def _sync_antenna_combo(self):
        """Set the Antenna combo back to the source's live port without
        re-triggering set_antenna (used when a switch is refused)."""
        combo = getattr(self, '_antenna_combo_box', None)
        if combo is None or self._source is None:
            return
        cur = self._source.current_antenna
        if cur in self._antenna_options:
            with _SignalBlocker(combo):
                combo.setCurrentIndex(self._antenna_options.index(cur))

    def get_center_freq(self):
        return self.center_freq

    def set_center_freq(self, center_freq):
        self.center_freq = center_freq
        self._fft_plot.set_frequency_range(self.center_freq, self.samp_rate)
        self._waterfall_plot.set_frequency_range(self.center_freq, self.samp_rate)
        if self._playback_mode:
            # Virtual retune: shift the file's baseband by the offset between
            # the requested center frequency and the file's original center.
            # rotator_cc multiplies samples by exp(j*phase_inc*n), so a
            # negative phase_inc shifts the spectrum down by the desired
            # offset. Outside the file's bandwidth the user just sees the
            # wrap-around / noise floor.
            import math
            offset_hz = self.center_freq - self._playback_center_freq
            phase_inc = -2.0 * math.pi * offset_hz / self.samp_rate
            self._rotator.set_phase_inc(phase_inc)
            return
        if self._source is not None:
            self._source.set_center_freq(self.center_freq)




def main(top_block_cls=dses_spectrum_analyzer, options=None):

    qapp = QtWidgets.QApplication(sys.argv)
    # Drive QStandardPaths.AppDataLocation to %APPDATA%/DSES_Analyzer (Windows)
    # / ~/Library/Application Support/DSES_Analyzer (mac) / ~/.local/share/...
    # Must be set BEFORE constructing the top block (which builds Settings).
    QtWidgets.QApplication.setApplicationName("DSES_Analyzer")
    QtWidgets.QApplication.setApplicationDisplayName(APP_NAME)
    QtWidgets.QApplication.setApplicationVersion(APP_VERSION)

    tb = top_block_cls()

    tb.start()
    tb.flowgraph_started.set()

    tb.show()
    _bring_to_front(tb)  # open in front (esp. macOS launched from a terminal)

    def sig_handler(sig=None, frame=None):
        # closeEvent doesn't fire on SIGINT/SIGTERM (e.g. Ctrl-C in the
        # terminal or closing the terminal window), so persist window geometry
        # and settings here too — otherwise quitting from the terminal loses
        # the latest configuration.
        try:
            tb._save_geometry()
        except Exception as exc:
            print(f"Settings save on signal failed: {exc}", file=sys.stderr)
        tb.stop()
        tb.wait()
        QtWidgets.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = QtCore.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec()

if __name__ == '__main__':
    main()
