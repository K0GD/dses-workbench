# DSES Pulsar Trip Report — Haswell, 2026-07-11 (+ 07-12 follow-up)

**Author:** Richard M Hambly (K0GD), with Claude Code (Mac session)
**Machines on site:** the macOS laptop + the **Linux drift-scan box**
(`DSES-Drift-Scan`, a Raspberry Pi 5, LXDE/Openbox on X11), both driving the
DSES 60-ft dish via an Ettus **USRP B210**.
**Purpose:** first live pulsar captures with the 1.1.x DSES Spectrum Analyzer +
`.fil` recording path, and shake-out of the field software.

> Handoff note for the **Windows machine / next release engineer:** everything
> below is on `origin` (this Mac has nothing unpushed). The code changes since
> 1.1.5 are the **1.1.6 changeset** (section 4). The Linux box is running a
> hand-patched 1.1.5 that 1.1.6 makes permanent. See §7 for open items.

---

## 1. Field observations (Haswell, 2026-07-11)

Two pulsars recorded live to SIGPROC filterbank (`.fil`) with the B210 through
the 60-ft dish. Common geometry: **256 channels, Integrate 16, 20 MHz bandwidth,
420 MHz center (410–430 MHz), tsamp = 256×16/20 MHz = 204.8 µs, 32-bit float**,
telescope_id 12 (→ Haswell). Format = live-channelized `.fil` (raw I/Q not
stored).

| Target | Local start | UTC (MJD) | Duration | Size | Notes |
|---|---|---|---|---|---|
| **B0329+54** (reference pulsar, J0332+5434) | 14:17 MDT | 20:17 (61232.8452) | 36.6 min (10,714,416 spectra) | 11.0 GB | bright northern reference; near-circumpolar from Haswell |
| **B0950+08** (J0953+0755) | 15:12 MDT | 21:12 (61232.8834) | 22.2 min (6,513,076 spectra) | 6.7 GB | chosen because it was transiting (~59° alt); bright, low-DM |

Target selection was done live from the catalog by computing current alt/az from
the Haswell site — B0950+08 was near transit and B0329+54 is the standard
reference. (Other cataloged pulsars were mostly too far south to observe from
Haswell's latitude.)

**Recording caveat (fixed later, see §5):** these were recorded with the app
build then on the box, which did **not** yet stamp the source name — the `.fil`
headers went out as `source_name = "capture"` with `src_raj/src_dej = 0`, and the
files were renamed to include the pulsar name afterward.

## 2. Linux drift-scan box — field software issues (diagnosed + fixed 07-11)

On site the Linux box showed: **dropdown boxes didn't work, the Help menu was
blank, and the app opened tiny in the top-left corner.** Diagnosed remotely over
**Tailscale SSH** (`dses@100.118.148.6`).

**Root cause — ONE condition:** the box is **headless** (no monitor; both HDMI
outputs `disconnected`) and viewed over **Splashtop/xrdp**. With no *connected*
output, Qt's RandR query returns a **0×0 screen** (`xrandr` shows a 1920×1080
framebuffer, `xdpyinfo` says 1920×1080, but Qt `primaryScreen().geometry()` is
`(0,0,0,0)`). A 0×0 screen collapses every Qt popup (combo dropdowns **and**
menus) to a 2×2 window at the origin, and made the window-geometry clamp shrink
the window. **Not app-logic bugs — a display-config symptom.**

**Fixes (deployed to the box directly via scp; also in the 1.1.6 code):**
- `launcher.sh` now **synthesizes a virtual monitor** (`xrandr --setmonitor`
  spanning the framebuffer) when no monitor is connected → Qt sees a real
  1920×1080 screen → popups + geometry work. Self-heals on every launch; skipped
  when a real monitor is attached. (commit **d7ede88**)
- The app **bails out of clamp/center when the screen is empty** so it can't
  mangle the window on a 0×0 screen. (commit **5c8cc6a**)
- Immediate workaround used on site: change any combo by keyboard (focus + ↑/↓).

The box had also been running a **stale 1.0.0**; it now runs the patched 1.1.5.
(Cutting 1.1.6 makes these fixes permanent via a normal install/update.)

## 3. Recording-panel features added (requested on site, built 07-12)

All in commit **db5dd83**:
- **Source name** field → sanitized into the filename (SigMF + `.fil`) **and**
  written to the SIGPROC `.fil` header `source_name` (PRESTO/prepfold read it) +
  the SigMF description. Blank = timestamp-only (unchanged).
- **Elapsed-time counter** (`H:MM:SS`) while recording, via a 1 Hz timer.
- **Red REC indicator** — the status turns white-on-red while a recording runs.
- **"Record for" duration** (minutes or `H:MM`) → **auto-stops** at the target
  with a live countdown. Blank = record until stopped.

Source name + duration persist in `[recording]` settings and lock while
recording. Logic unit-tested; panel builds and runs in playback. **Not yet
exercised on a live B210** — verify the record→red-light→counter→auto-stop→file
flow on hardware before shipping.

## 4. The 1.1.6 changeset (everything on `origin` since 1.1.5 = 056501d)

**Code (ship in 1.1.6):**
- `5c8cc6a` — geometry: don't clamp/center to an empty (0×0) screen (headless).
- `d7ede88` — `launcher.sh`: synthesize a virtual monitor on headless Linux.
- `db5dd83` — recording panel: source name in filename + `.fil` header, elapsed
  counter, red REC, timed auto-stop.
- `217ff51` — **Sweep mode restored** (stepped wide-spectrum scan; the "scan
  mode" that had been lost — recovered from `origin/recovered/sweep-mode`).
- `c134116` — Sweep: Help text + neutralize baseline & clear markers while sweeping.
- `23580ed` — Sweep: clamp Start/Stop to the radio's tuning range.
- `9f4d1f7` — `sigproc_fil`: derive `src_raj/src_dej` from the source name for
  the `.fil` header (`radec_from_name`).

(The 1.1.5 release already contains the earlier fixes: launcher-permission
self-heal, α-slider-vanishing fix, double-click marker clear, and the X11/LXDE
frame-coordinate window-geometry fix.)

**Docs/handoff commits (not shipped):** several `CLAUDE.md` updates recording the
Linux root-cause, the cross-machine rules, and the STATE-OF-PLAY.

## 5. Data processing (Mac, 2026-07-12)

**Header fix.** The two `.fil` files were rewritten to **exactly what 1.1.6
would have recorded** — `source_name` set and `src_raj/src_dej` derived via
`sigproc_fil.radec_from_name` (byte-identical header; the ~11 GB data payloads
were copied unchanged and verified head+tail). Headers now read
`B0329+54 → 03:29:00 +54:00:00` and `B0950+08 → 09:50:00 +08:00:00`
(name-derived B1950-ish positions).

**Folds (PRESTO `prepfold`, on the Mac's `presto` env, PRESTO v5.0.2):**

| Target | Fold | Result |
|---|---|---|
| **B0329+54** | topocentric (`-topo -p 0.714520 -dm 26.7641`) | **~20.1 σ** (Prob(noise) < 4.5×10⁻⁹⁰), P_topo 714.42 ms, DM peak ≈ 26 |
| **B0329+54** | barycentric par fold (`-par J0332+5434.par`) | **~19.9 σ**, folded against the real ephemeris |
| **B0950+08** | topocentric (`-topo -p 0.253065 -dm 2.97`) | **~9.7 σ** (Prob(noise) < 1.8×10⁻²²), P_topo 252.93 ms |
| **B0950+08** | barycentric par fold (`-par J0953+0755.par`) | **~9.9 σ** (Prob(noise) < 2.5×10⁻²³), P_topo 252.94 ms; DM slides to ~0 (low DM over 20 MHz) |

No J0953+0755 ephemeris existed anywhere (TEMPO's `tzpar/` here has almost none),
so I built a minimal one in **`~/work/J0953+0755.par`** from the catalog position
+ F0/DM — an accurate *position* is what a barycentric fold needs, and prepfold's
search handles the rest. B0329 used the existing `~/work/J0332+5434.par`. Both
par folds run **warning-free** now that TEMPO's UT1 table is current (below).

**Both pulsars clearly detected in both topocentric AND barycentric-ephemeris
folds — the record → `.fil` → PRESTO pipeline is validated end-to-end on real
dish data.** Full prepfold diagnostic plots are saved as **PDFs alongside the
`.fil` files** in `~/Documents/DSES_SA_Recordings/` — for each recording a
`…prepfold.pdf` (topocentric) and a `…prepfold-par.pdf` (barycentric); the
`.pfd`/`.bestprof` working products stay in the `folds/` subdir.

**TEMPO fixed for barycentric folds (Mac):**
- `tempo` must be on `PATH` — PRESTO calls it by bare name (it lives in the
  `presto` env). Without it, `prepfold -par`/`prepdata` fail silently.
- `~/tempo/clock/ut1.dat` was **stale** (ended MJD 59304 / 2021), so 2026 obs hit
  "MJD outside parameter validity range" and didn't barycenter. **Updated to MJD
  61599 (2027)** from current IERS EOP (`datacenter.iers.org`: C04 final +
  finals2000A predictions) via TEMPO's own `make_ut1`; old table backed up. The
  validity warning is now gone. (Redo this ~yearly as obs pass the table's end.)

## 6. Machine / environment state (as of 07-12)

- **macOS:** production install on **1.1.5**; dev checkout at `origin` HEAD; TEMPO
  `ut1.dat` now current to 2027; full PRESTO toolchain works.
- **Linux drift-scan box:** hand-patched **1.1.5** (virtual-monitor launcher +
  geometry safeguard scp'd on) — a stock re-install/update would revert these, so
  **1.1.6 makes them permanent**. Reachable at `dses@100.118.148.6` (Tailscale).
- **Windows dev box:** did the Sweep-mode recovery, RA/Dec-in-header, and B210
  hardware testing (B210 s/n 8003886); smoke-tested `make-release.ps1`.
- **Server (gpstime):** latest published release is **1.1.5**.

## 7. Open items — for the 1.1.6 release (Windows)

1. **Cut and publish 1.1.6** — bump `APP_VERSION`/`DOC_VERSION`/Installing.md,
   rebuild the guide PDF, build the zip, regen `.sha256` + `manifest.json`, push,
   scp to gpstime + verify URLs. Bundles §4. Per the STATE-OF-PLAY, this is the
   only remaining dev item.
2. **B210 verification of the new recording flow** (red REC / counter /
   "record for" auto-stop / source-name-in-filename + header) — the Windows B210
   testing covered recording + Sweep; confirm the timed-recording specifics.
3. After 1.1.6 ships, the **Linux box** should install it (fresh from the
   Mac/Windows-built zip) so its patches are official.

## 8. Science follow-ups (not blocking the release)

- **Barycentric timing:** the `-par` fold works and is now warning-free, but a
  proper timing solution (TOAs, real spin-down) wants a longer/repeat baseline;
  the short 37-min track is detection-grade, not timing-grade.
- The header `src_raj/src_dej` are **name-derived** (arcmin-ish, B1950). For
  precise pointing/timing on B0329, use the exact `~/work/J0332+5434.par`.
- Consider re-observing B0950+08 longer (it scintillates strongly).
