#!/usr/bin/env python3
"""
fold_analysis.py -- the DSES canned PRESTO pipeline ("is the recording good?").

One code path serves three app features (v1.1.9 roadmap items):
  * end-of-recording automatic post-processing ("Analyze when done"),
  * the mid-recording quick look (fold a snapshot WITHOUT touching the
    still-growing .fil),
  * self-contained result PDFs (chart + commands + numbers + verdict via
    fold_pdf.py, per the CLAUDE.md fold-PDF convention).

The pipeline is the sequence hand-run for the Haswell validation and refined
by Dan Layne's review: readfile sanity -> rfifind mask -> band-edge zap ->
prepfold against the pulsar catalog -> parse -> verdict. PRESTO runs natively
where installed (Mac/Linux) or through WSL on Windows (presto_bridge). All
functions are Qt-free so the pipeline is testable headless; the app wraps it
in a worker thread.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sigproc_fil import read_sigproc_header, radec_from_name

# Verdict thresholds on prepfold's reduced chi-squared (flat profile = 1).
# Calibrated on the Haswell recordings: B0329+54 gave 8.5-16.8 across folds,
# B0950+08 (real but weak) 3.4-3.9. Below ~1.5 nothing periodic is present.
CHI2_DETECTION = 5.0
CHI2_CANDIDATE = 1.8
EDGE_ZAP_FRACTION = 0.05          # zap this fraction of channels at EACH edge
QUICKLOOK_MIN_SECONDS = 60.0      # need at least this much data to bother


class PrestoUnavailable(RuntimeError):
    pass


class PrestoRunner:
    """Run PRESTO tools natively (Mac/Linux) or via WSL (Windows)."""

    def __init__(self):
        self.mode = None
        if shutil.which("prepfold"):
            self.mode = "native"
        elif sys.platform == "win32":
            try:
                from presto import presto_bridge
            except ImportError:
                sys.path.insert(0, str(Path(__file__).parent / "presto"))
                try:
                    import presto_bridge
                except ImportError:
                    presto_bridge = None
            else:
                presto_bridge = presto_bridge
            if presto_bridge is not None and presto_bridge.wsl_available():
                probe = presto_bridge.run("bash", "-c", "command -v prepfold")
                if probe.returncode == 0 and probe.stdout.strip():
                    self.mode = "wsl"
                    self._bridge = presto_bridge

    @property
    def available(self):
        return self.mode is not None

    def describe(self):
        return {"native": "native PRESTO on PATH",
                "wsl": "PRESTO in WSL via presto_bridge",
                None: "PRESTO not found (install it, or on Windows run "
                      "presto/build_presto.sh inside WSL)"}[self.mode]

    def run(self, tool, *args, cwd=None, timeout=3600, nice=True):
        """Run a tool low-priority (protects a live recording) with cwd set
        so PRESTO products land in the analysis directory."""
        if self.mode == "native":
            import subprocess
            cmd = ([tool] + [str(a) for a in args])
            if nice and sys.platform != "win32":
                cmd = ["nice", "-n", "10"] + cmd
            return subprocess.run(cmd, cwd=cwd, capture_output=True,
                                  text=True, timeout=timeout)
        if self.mode == "wsl":
            parts = (("nice", "-n", "10", tool) if nice else (tool,))
            return self._bridge.run(*parts, *args, cwd_win=cwd,
                                    timeout=timeout)
        raise PrestoUnavailable(self.describe())

    def render_ps_to_png(self, ps_path, png_path, dpi=120):
        """prepfold's plot is PostScript; gs renders it. Under WSL, gs's
        AppArmor profile often can't write under /mnt/*, so render to the
        WSL home dir and copy out."""
        if self.mode == "native":
            r = self.run("gs", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m",
                         f"-r{dpi}", f"-sOutputFile={png_path}", ps_path,
                         nice=False)
            return r.returncode == 0 and os.path.exists(png_path)
        if self.mode == "wsl":
            tmp = "/root/dses_fold_render.png"
            inner = ("gs -dBATCH -dNOPAUSE -sDEVICE=png16m "
                     f"-r{dpi} -sOutputFile={tmp} "
                     + self._bridge.to_wsl_path(str(ps_path))
                     + " >/dev/null 2>&1 && cp " + tmp + " "
                     + self._bridge.to_wsl_path(str(png_path)))
            r = self._bridge._exec(inner)
            return r.returncode == 0 and os.path.exists(png_path)
        raise PrestoUnavailable(self.describe())


def snapshot_fil(src, dst):
    """Copy a growing .fil to `dst`, truncated to a whole number of complete
    spectra — always a valid filterbank even while the writer appends
    (whole rows + flush; SIGPROC headers carry no sample count)."""
    hdr = read_sigproc_header(src)
    row = hdr["nchans"] * hdr["nbits"] // 8
    hdr_len = hdr["_header_bytes"]
    size = os.path.getsize(src)
    nrows = (size - hdr_len) // row
    if nrows <= 0:
        raise ValueError("no complete spectra in the file yet")
    total = hdr_len + nrows * row
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        remaining = total
        while remaining > 0:
            buf = fin.read(min(1 << 22, remaining))
            if not buf:
                break
            fout.write(buf)
            remaining -= len(buf)
    return {"rows": nrows, "seconds": nrows * hdr["tsamp"], "header": hdr}


def _nsub_for(nchans, cap=128):
    """Largest divisor of nchans that is <= cap. prepfold refuses to pick
    -nsub itself for awkward channel counts (e.g. 2044 = 2^2*7*73)."""
    best = 1
    d = 1
    while d * d <= nchans:
        if nchans % d == 0:
            for v in (d, nchans // d):
                if v <= cap and v > best:
                    best = v
        d += 1
    return best


def _save_log(workdir, name, cp):
    """Persist a tool's stdout/stderr next to its products so a failed step
    is never opaque."""
    try:
        with open(Path(workdir) / f"{name}.log", "w", encoding="utf-8",
                  errors="replace") as f:
            f.write(f"# exit code: {cp.returncode}\n\n")
            f.write(cp.stdout or "")
            if (cp.stderr or "").strip():
                f.write("\n\n# ---- stderr ----\n" + cp.stderr)
    except OSError:
        pass


def _parse_prepfold_stdout(text):
    out = {}
    m = re.search(r"Maximum reduced chi-squared found\s*=\s*([0-9.]+)", text)
    if m:
        out["chi2_red"] = float(m.group(1))
    m = re.search(r"Best DM\s*\(pc cm\^-3\)\s*=\s*([0-9.]+)", text)
    if m:
        out["best_dm"] = float(m.group(1))
    m = re.search(r"Best period\s*\(s\)\s*=\s*([0-9.]+)", text)
    if m:
        out["best_p_s"] = float(m.group(1))
    m = re.search(r"\(DM\s*=\s*([0-9.]+)\)", text)
    if m:
        out["catalog_dm"] = float(m.group(1))
    return out


def _verdict(results, source_name, quick, catalog_fold=False):
    chi2 = results.get("chi2_red")
    if chi2 is None:
        return ("NO FOLD", "The fold step did not complete; see prepfold.log "
                           "in the analysis folder.")
    what = "quick-look fold" if quick else "fold"
    # RFI guards for catalog folds (the hard-won B0950+08 / bench lessons):
    # a real pulsar detection optimizes NEAR its catalog DM; terrestrial
    # signals (carriers, spurs, test signals) rail to DM ~ 0 no matter how
    # enormous their chi-squared gets.
    best_dm = results.get("best_dm")
    cat = results.get("catalog_dm")
    if catalog_fold and chi2 >= CHI2_CANDIDATE and best_dm is not None:
        if best_dm < 1.0:
            return ("TERRESTRIAL SIGNAL",
                    f"Strong periodicity (reduced chi-squared {chi2:.1f}) "
                    f"but it optimizes to DM ≈ 0 — zero dispersion means a "
                    f"LOCAL signal (RFI, a carrier, a test source), not "
                    f"{source_name}. Inspect the band for interference; this "
                    f"is not a pulsar detection.")
        if cat and abs(best_dm - cat) > max(5.0, 0.5 * cat):
            return ("SUSPECT",
                    f"Periodic signal (reduced chi-squared {chi2:.1f}) but "
                    f"its best DM ({best_dm:.1f}) is far from the catalog "
                    f"value ({cat:.1f}) — treat with suspicion: possible "
                    f"RFI, or a corrupted fold. Manual review recommended.")
    if chi2 >= CHI2_DETECTION:
        return ("DETECTION",
                f"Strong periodic signal: reduced chi-squared {chi2:.2f} "
                f"(flat noise = 1). The {what} of {source_name} looks like a "
                f"solid detection — the recording is good.")
    if chi2 >= CHI2_CANDIDATE:
        return ("CANDIDATE",
                f"Possible signal: reduced chi-squared {chi2:.2f}. Treat as "
                f"a candidate, not a publishable detection — weak pulsars "
                f"(scintillation, short integration) can sit here even in a "
                f"good recording. More integration time is the usual cure.")
    return ("NO DETECTION",
            f"No significant periodicity (reduced chi-squared {chi2:.2f}). "
            f"NOTE: no detection does NOT mean a bad recording — a weak or "
            f"scintillating pulsar can be invisible in a short stretch. The "
            f"readfile/rfifind checks above say whether the DATA is healthy.")


def analyze_fil(fil_path, *, source_name="", runner=None, quick=False,
                fold_p_s=None, fold_dm=None,
                progress=lambda msg: None):
    """Run the canned pipeline on `fil_path`. Returns a result dict; writes
    `<basename>_prepfold.pdf` (or `_quicklook.pdf`) next to the .fil and
    leaves working products in `<basename>_analysis/`."""
    t0 = time.monotonic()
    fil_path = Path(fil_path)
    runner = runner or PrestoRunner()
    if not runner.available:
        raise PrestoUnavailable(runner.describe())

    hdr = read_sigproc_header(fil_path)
    nchans = hdr["nchans"]
    dur_s = None  # readfile reports it; compute locally too
    nrows = (os.path.getsize(fil_path) - hdr["_header_bytes"]) \
        // (nchans * hdr["nbits"] // 8)
    dur_s = nrows * hdr["tsamp"]

    workdir = fil_path.parent / (fil_path.stem + "_analysis")
    workdir.mkdir(exist_ok=True)
    base = fil_path.stem
    cmds = []

    progress("readfile sanity check…")
    r = runner.run("readfile", str(fil_path), cwd=str(workdir), timeout=600)
    _save_log(workdir, "readfile", r)
    cmds.append("readfile " + fil_path.name)
    readfile_ok = (r.returncode == 0
                   and re.search(r"Time per file|Total time",
                                 (r.stdout or "")) is not None)

    progress("rfifind RFI mask…")
    r = runner.run("rfifind", "-time", "2.0", "-o", base, str(fil_path),
                   cwd=str(workdir), timeout=3600)
    _save_log(workdir, "rfifind", r)
    cmds.append(f"rfifind -time 2.0 -o {base} {fil_path.name}")
    mask = workdir / f"{base}_rfifind.mask"
    mask_ok = r.returncode == 0 and mask.exists()
    m = re.search(r"Number of\s+bad\s+intervals:\s*\d+\s*\(\s*([0-9.]+)%\)",
                  (r.stdout or ""))
    masked_pct = float(m.group(1)) if m else None

    # Band-edge zap: outer EDGE_ZAP_FRACTION of channels on each side
    # (anti-alias skirts; PRESTO channel 0 = lowest frequency).
    zap_n = max(1, int(round(nchans * EDGE_ZAP_FRACTION)))
    ignorechan = f"0:{zap_n - 1},{nchans - zap_n}:{nchans - 1}"

    results = {}
    fold_png = None
    # Fold target: a catalog pulsar name (B/J designation) or a manual
    # period/DM override (magnetars, sources without catalog ephemerides,
    # synthetic tests).
    manual = fold_p_s is not None
    is_psr = manual or (bool(source_name)
                        and radec_from_name(source_name) != (0.0, 0.0))
    if is_psr:
        nsub = _nsub_for(nchans)
        if manual:
            source_name = source_name or f"{fold_p_s*1e3:.1f} ms source"
            progress(f"prepfold -topo -p {fold_p_s}…")
            args = ["-noxwin", "-topo", "-p", f"{fold_p_s}",
                    "-dm", f"{fold_dm or 0.0}", "-nsub", str(nsub),
                    "-ignorechan", ignorechan, "-o", base + "_fold"]
        else:
            progress(f"prepfold -psr {source_name}…")
            args = ["-noxwin", "-psr", source_name, "-nsub", str(nsub),
                    "-ignorechan", ignorechan, "-o", base + "_fold"]
        if mask_ok:
            args += ["-mask", str(mask)]
        r = runner.run("prepfold", *args, str(fil_path),
                       cwd=str(workdir), timeout=7200)
        _save_log(workdir, "prepfold", r)
        cmds.append("prepfold " + " ".join(
            a if not str(a).endswith(".mask") else Path(a).name
            for a in args) + " " + fil_path.name)
        results = _parse_prepfold_stdout((r.stdout or "") + (r.stderr or ""))
        # Locate the plot; render the .ps if prepfold's own png failed.
        pngs = sorted(workdir.glob(base + "_fold*.png"))
        if pngs:
            fold_png = pngs[0]
        else:
            pss = sorted(workdir.glob(base + "_fold*.ps"))
            if pss:
                progress("rendering fold plot…")
                cand = workdir / (pss[0].stem + ".png")
                if runner.render_ps_to_png(pss[0], cand):
                    fold_png = cand

    label, verdict_text = _verdict(results, source_name, quick,
                                   catalog_fold=not manual) if is_psr \
        else ("DATA CHECK",
              "No catalog pulsar name on this recording — ran the data-"
              "health checks only (readfile + rfifind). Set a Source name "
              "before recording to get an automatic fold.")

    # ----- build the self-contained PDF --------------------------------
    progress("writing PDF…")
    fmin = hdr["fch1"] + (nchans - 1) * hdr["foff"]
    meta = [
        f"|Source:   {source_name or '(none)'}    File: {fil_path.name}",
        f"|Band:     {fmin:.3f}-{hdr['fch1']:.3f} MHz, {nchans} channels"
        f"    tsamp {hdr['tsamp']*1e6:.1f} us    length {dur_s:.1f} s"
        f" ({nrows} spectra)",
        f"|Start:    MJD {hdr['tstart']:.6f}    telescope_id"
        f" {hdr.get('telescope_id', '?')} (DSES convention: 12 = Haswell)",
    ]
    tbl = ["|Check                Result",
           f"|readfile             {'OK' if readfile_ok else 'FAILED'}",
           f"|rfifind mask         "
           + (f"OK ({masked_pct:.2f}% flagged)" if mask_ok and masked_pct
              is not None else ("OK" if mask_ok else "FAILED")),
           f"|band-edge zap        outer {EDGE_ZAP_FRACTION*100:.0f}% each"
           f" side ({ignorechan})"]
    if results:
        tbl.append(f"|reduced chi-squared  {results.get('chi2_red', '—')}")
        if "best_dm" in results:
            cat = results.get("catalog_dm")
            tbl.append(f"|best DM              {results['best_dm']:.2f}"
                       + (f"   (catalog {cat:.2f})" if cat else ""))
        if "best_p_s" in results:
            tbl.append(f"|best period          {results['best_p_s']*1e3:.4f} ms")
    commentary = "\n".join([
        "## What this is",
        ("Mid-recording QUICK LOOK on a snapshot of the still-growing "
         "recording." if quick else
         "Automatic end-of-recording analysis.") +
        " Generated by the DSES Spectrum Analyzer's canned PRESTO pipeline "
        "(readfile sanity, rfifind RFI mask, band-edge zap, catalog fold). "
        f"Analyzed {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC in "
        f"{time.monotonic()-t0:.0f} s.",
        "",
        "## Recording", *meta,
        "",
        "## Commands", *("|" + c for c in cmds),
        "",
        "## Results", *tbl,
        "",
        f"## Verdict: {label}",
        verdict_text,
        "",
        "Working products (mask, .pfd, .bestprof, plots) are in "
        f"{workdir.name}/ beside the recording.",
    ])
    suffix = "_quicklook.pdf" if quick else "_prepfold.pdf"
    pdf_path = fil_path.parent / (base + suffix)
    charts = [(str(fold_png),
               f"{source_name} — canned catalog fold (mask + edge zap)")] \
        if fold_png else []
    import fold_pdf
    fold_pdf.build_pdf(str(pdf_path),
                       f"{base} — {'quick look' if quick else 'analysis'}",
                       commentary, charts)

    return {"verdict": label, "verdict_text": verdict_text,
            "pdf": str(pdf_path), "workdir": str(workdir),
            "chi2_red": results.get("chi2_red"),
            "best_dm": results.get("best_dm"),
            "catalog_dm": results.get("catalog_dm"),
            "best_p_s": results.get("best_p_s"),
            "readfile_ok": readfile_ok, "mask_ok": mask_ok,
            "masked_pct": masked_pct, "duration_s": dur_s,
            "elapsed_s": time.monotonic() - t0}
