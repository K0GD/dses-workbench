# B210 Spectrum Analyzer — Installation Guide

**Version 1.0.0**
Author: Richard M Hambly (K0GD) — rick@cnssys.com
License: GPL-3.0-or-later

This document covers:

- How to install the B210 Spectrum Analyzer on Windows 11, Linux, and macOS (Intel and Apple Silicon).
- How to update to a new version.
- Common troubleshooting and a reference for advanced settings.

The application itself is one Python file plus a few launchers and an icon. The heavy machinery — GNU Radio, UHD, SoapySDR, PySide6, NumPy, SciPy — is supplied by **Radioconda**, which you install separately as a one-time prerequisite.

**Supported radios.** The program is designed around the Ettus USRP B210 but also drives any SoapySDR-compatible receiver: SDRPlay RSP1A / RSP1B / RSPduo / RSPdx (with one extra setup step — see §1A), RTL-SDR, HackRF, Airspy / Airspy HF+, BladeRF, LimeSDR, and PlutoSDR. The sample-rate combo and gain slider adapt automatically to whichever device you pick at startup.


## 1. What the recipient needs to know first

Each recipient performs **two installs**, in this order (plus a third optional step if you're using SDRPlay):

1. **Install Radioconda** (one-time). Radioconda is a curated conda distribution that bundles GNU Radio, UHD, SoapySDR, and the surrounding scientific Python stack for software-defined radio. We require version 4.8 or newer (it ships with UHD ≥ 4.8). Download: <https://github.com/ryanvolz/radioconda/releases>.
2. **Install this app**, which is just a small zip of Python and launcher scripts.
3. **If using SDRPlay only:** install the SDRplay API + SoapySDRPlay module (see §1A). Other supported radios work without any extra setup.

Updates to the app afterwards are a small zip replace — Radioconda does not need to be re-installed for every release.

### System requirements

| Component | Minimum |
|---|---|
| OS | Windows 11; Ubuntu/Debian/Fedora/Arch (current); macOS 11 Big Sur or newer |
| CPU | x86_64 *or* Apple Silicon (M1/M2/M3/M4) |
| RAM | 4 GB free |
| USB | One USB 3.0 port (5 Gbps) for the B210 |
| Hardware | Ettus USRP B210 *or* any SoapySDR-supported receiver (SDRPlay RSPx, RTL-SDR, HackRF, Airspy, BladeRF, LimeSDR, PlutoSDR). With one radio attached the app uses it silently; with several, a picker appears. See §8 for details. |
| Disk | ~3 GB for Radioconda, plus ~1 MB for this app |
| Display | 1280 × 800 minimum; 14″ MacBook Pro is the layout target |


## 1A. Optional: extra setup for SDRPlay (RSP1A / RSP1B / RSPduo)

If you're using an **SDRPlay** receiver (RSP1A, RSP1B, RSPduo, or RSPdx), you need two extra pieces beyond Radioconda. **Skip this section entirely if you're only using a B210, RTL-SDR, HackRF, Airspy, BladeRF, LimeSDR, or PlutoSDR — those work out of the box once Radioconda is installed.**

### 1A.1 Install the SDRplay API

SDRPlay devices need the manufacturer's proprietary API driver. Download and install it from <https://www.sdrplay.com/api/> — pick the installer for your OS.

- **Windows:** run the `.exe` installer; accept defaults. A reboot may be needed.
- **Linux:** run the `.run` installer with `sudo`.
- **macOS:** run the `.pkg` installer.

After installation, verify the API can see your unit with the SDRplay Service / Status app (Windows) or `SDRplayService` (Linux/macOS). You should see your RSP listed.

### 1A.2 Install the SoapySDRPlay module

This is the glue between SDRplay's API and the SoapySDR layer the program uses.

```text
Windows / Linux / macOS — from an activated Radioconda prompt:
  conda install -c conda-forge soapysdr-module-sdrplay
```

Verify it loaded:

```text
SoapySDRUtil --info
```

…should list `sdrplay` in the "Available factories" line. If it doesn't, the API install in §1A.1 didn't take — recheck that.

When you launch the spectrum analyzer with an RSP attached, it will appear in the device picker as e.g. `RSPduo — 1234567 [sdrplay]`.


## 2. Installing Radioconda

### 2.1 Windows 11

1. Download `radioconda-Windows-x86_64.exe` from the Radioconda releases page.
2. Double-click the installer. Accept defaults; the installer offers to put Radioconda under `C:\ProgramData\radioconda` (system-wide) or `%LOCALAPPDATA%\radioconda` (per-user). Either works; the app's launcher checks both.
3. After the install finishes, plug the B210 into a USB 3 port. The first time you do this, Windows will silently install the UHD driver from the Radioconda install. No prompt should appear.
4. Verify the B210 is detected by opening the **Anaconda Prompt (Radioconda)** shortcut from the Start menu and running:

   ```text
   uhd_find_devices
   ```

   You should see one device with `serial: 3273A91`.

### 2.2 Linux

1. Download `radioconda-Linux-x86_64.sh` from the releases page.
2. From a terminal:

   ```bash
   bash radioconda-Linux-x86_64.sh
   ```

   Accept the license and let it install to `~/radioconda` (the launcher checks this path automatically).
3. **USB permissions for the B210.** Radioconda installs the Ettus udev rules, but they need to be activated:

   ```bash
   sudo cp ~/radioconda/lib/uhd/utils/uhd-usrp.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

   Without this step, you'll get permission errors when the B210 is plugged in.
4. Add yourself to the `usrp` (or `plugdev`, depending on distro) group if your distribution uses one. Log out and back in.
5. Plug in the B210 and verify:

   ```bash
   ~/radioconda/bin/uhd_find_devices
   ```

### 2.3 macOS (Intel and Apple Silicon)

Radioconda publishes builds for both architectures:

- `radioconda-MacOSX-x86_64.sh` — Intel Macs.
- `radioconda-MacOSX-arm64.sh` — Apple Silicon Macs (M1/M2/M3/M4).

There is **no functional difference** between the two for our purposes. Pick the file that matches your CPU (`uname -m` prints `x86_64` or `arm64`).

1. From a terminal:

   ```bash
   bash radioconda-MacOSX-<arch>.sh
   ```

2. Accept the default install location (`~/radioconda`).
3. Plug in the B210. macOS does not require a driver install.
4. Verify:

   ```bash
   ~/radioconda/bin/uhd_find_devices
   ```

5. **Quarantine note.** If you ever see a Gatekeeper "cannot verify developer" dialog on a Radioconda binary, run:

   ```bash
   xattr -dr com.apple.quarantine ~/radioconda
   ```


## 3. Installing the B210 Spectrum Analyzer

You will have received a zip file named `b210-spectrum-analyzer-<version>.zip` (e.g. `b210-spectrum-analyzer-1.0.0.zip`).

### 3.1 Windows 11

1. Extract the zip anywhere you have write permission. A common choice is `Documents\B210-Spectrum-Analyzer`. The extracted folder will be `b210-spectrum-analyzer-1.0.0\` and will contain `b210_spectrum_analyzer.py`, `launcher.bat`, `launcher.ps1`, `install-shortcut.ps1`, `LICENSE`, the `icons\` folder, and this guide.
2. Double-click **`launcher.bat`** to start the application.
3. The first time you run it, the launcher searches for Radioconda in this order: the `RADIOCONDA_ROOT` environment variable, any currently-activated conda env, `%LOCALAPPDATA%\radioconda`, `C:\ProgramData\radioconda`, `%USERPROFILE%\radioconda`, a cached config file, then `conda info --base` if `conda` is on PATH. If none of these find a working install, you'll get a prompt asking for the path; type it in and the launcher remembers it for next time.
4. (Optional) Right-click **`install-shortcut.ps1`** → "Run with PowerShell" to put a "B210 Spectrum Analyzer" shortcut on your desktop and Start menu.

After the first run, the app's window opens with the spectrum and waterfall plots. Tuning, sample-rate, gain, and recording controls are in the sidebar on the right.

### 3.2 Linux

1. Extract the zip:

   ```bash
   unzip b210-spectrum-analyzer-1.0.0.zip
   cd b210-spectrum-analyzer-1.0.0
   chmod +x launcher.sh
   ```

2. Launch:

   ```bash
   ./launcher.sh
   ```

3. (Optional) Install a desktop entry so the app appears in your application menu:

   ```bash
   INSTALL_DIR="$(pwd)"
   sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" b210-spectrum-analyzer.desktop \
       > ~/.local/share/applications/b210-spectrum-analyzer.desktop
   update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
   ```

   (The `.desktop` file uses `__INSTALL_DIR__` as a placeholder so the launch path is correct on whichever machine installs it. The `sed` line substitutes the current directory into the placeholder.)

### 3.3 macOS

The steps are the same as Linux:

```bash
unzip b210-spectrum-analyzer-1.0.0.zip
cd b210-spectrum-analyzer-1.0.0
chmod +x launcher.sh
./launcher.sh
```

On Apple Silicon, **make sure** you installed the `arm64` build of Radioconda. Mixing an `x86_64` Radioconda with a native `arm64` Python or Qt will produce confusing errors at startup. There is no Rosetta-only step required if both halves match the CPU.

If the Finder warns about an unidentified developer when running `launcher.sh`, clear the quarantine attribute on the unzipped folder:

```bash
xattr -dr com.apple.quarantine b210-spectrum-analyzer-1.0.0
```


## 4. First-run checklist

Regardless of OS, before declaring the install good:

- The window title bar reads `B210 Spectrum Analyzer — v1.0.0 — B210 Spectrum Analyzer`. The version number must match the bundle you installed.
- Pull up **Help → User Guide** from the menu bar. The guide should open.
- Pull up **Help → About**. The author, version, license, and the path to the settings file should be readable.
- The spectrum plot should show live data (not a flat line at −140 dB). If it's flat, the B210 isn't streaming — see Troubleshooting §6.
- Click the **408 MHz** preset under Pulsar Band. The center frequency should retune and the trace should redraw.


## 5. Updating to a new version

### Auto-update notifications

The program checks for new versions at launch (no more than once per 24 hours). If a newer version is available, a small dialog opens with the release notes, a button to **Open Download Page** in your browser, a **Skip this version** button (won't nag again about that specific version), and a **Remind me later** button.

You can also trigger a check at any time via **Help → Check for Updates…**.

The check is read-only — the program never auto-downloads or auto-installs anything. To disable the auto-check entirely, edit your `settings.ini` and set `auto_check = false` under `[updates]`.

### Performing the update

Each release is a self-contained zip. To update:

1. **Close** the running app.
2. **Extract** the new zip alongside the old one (or over the top of the old folder). The new folder is named with the new version (e.g. `b210-spectrum-analyzer-1.0.1`).
3. **Run** `launcher.bat` or `launcher.sh` from the **new** folder.

### What is preserved across versions

Your settings and window geometry are kept outside the app folder, so updates never wipe them. The on-disk locations are:

| OS | Settings file |
|---|---|
| Windows | `%APPDATA%\B210Analyzer\settings.ini` |
| macOS | `~/Library/Application Support/B210Analyzer/settings.ini` |
| Linux | `~/.local/share/B210Analyzer/settings.ini` |

The settings file is plain text and editable with any editor while the app is closed. To reset everything to defaults, either delete the file or use **Help → About → Restore Defaults…** in the running app.

Window geometry is stored separately by Qt (`HKEY_CURRENT_USER\Software\gnuradio\flowgraphs\b210_spectrum_analyzer` on Windows; the equivalent QSettings storage on Mac/Linux). You don't need to touch it.

### Backing up your settings

The settings file is small (~1 KB). Copy it somewhere before a major upgrade if you want a quick rollback path:

```text
Windows:  copy "%APPDATA%\B210Analyzer\settings.ini" "%USERPROFILE%\Desktop\settings.ini.bak"
macOS:    cp "~/Library/Application Support/B210Analyzer/settings.ini" ~/Desktop/settings.ini.bak
Linux:    cp ~/.local/share/B210Analyzer/settings.ini ~/Desktop/settings.ini.bak
```


## 6. Troubleshooting

### "Radioconda not found in standard locations"

The launcher couldn't auto-detect a Radioconda install. Either:

- Install Radioconda to one of the standard paths the launcher checks (see §3.1 / §3.2 / §3.3), **or**
- Type the path when the launcher prompts you on first run, **or**
- Set the `RADIOCONDA_ROOT` environment variable to the install root before launching.

### "No UHD Devices Found"

The OS doesn't see the B210. In order:

1. Unplug the B210 from USB. Wait 5 seconds. Plug it back in. UHD's USB endpoint can hang on some systems after an abrupt kill of the previous run.
2. Make sure you're using a USB 3 port (not USB 2 — the B210 will be flaky at high sample rates).
3. From a terminal:

   ```text
   Windows:  C:\ProgramData\radioconda\Library\bin\uhd_find_devices.exe
   Linux:    ~/radioconda/bin/uhd_find_devices
   macOS:    ~/radioconda/bin/uhd_find_devices
   ```

   If `uhd_find_devices` doesn't see it either, the problem is below our software — check the B210's LEDs and try a different USB cable.

### Persistent "O" overflows at high sample rates

Some "O" characters in the Overflow box on the right sidebar at startup are normal as the USB pipe warms up. A continuous stream during steady-state operation usually means the host can't keep up with the sample rate:

- USB 2 ports cannot sustain 20 or 25 MS/s. Move to a USB 3 port.
- Other USB devices on the same controller (especially other 5 Gbps devices, or a heavily used external drive) compete for bandwidth. Move the B210 to its own controller if you have one.
- Reduce sample rate to 10 MHz or 16 MHz.

The Overflow box auto-clears after 15 seconds of no new overflows, so once the rate is stable you should see the box empty.

### Spectrum looks flat at −140 dB

The GR flow graph is running but no samples are arriving. Usual causes:

- The B210 is in a powered-but-disconnected state. Unplug and replug.
- Antenna is disconnected (this app uses RX2 by default). Confirm a cable is on RX2.
- Sample rate is set to a value the B210 can't actually achieve. Try 20 MHz.

### macOS: "developer cannot be verified"

```bash
xattr -dr com.apple.quarantine /path/to/b210-spectrum-analyzer-1.0.0
```

### Settings won't persist

Settings should be saved automatically on every change and on app close. If they aren't:

- Check the path printed in **Help → About**. The file should exist and be writable.
- If the directory's parent doesn't exist, the app will fail to create it silently. On first run after install, click **Help → About → Open Settings Folder** to verify it opens cleanly.


## 7. Appendix A — Settings file reference

The settings INI is plain text and editable while the app is closed. Sections:

- `[tuning]` — preset/coarse/fine/manual frequency in Hz.
- `[rx]` — sample rate in Hz, RX gain in dB, `device_driver` (e.g. `uhd_b200`, `sdrplay`, `rtlsdr`), `device_serial`.
- `[recording]` — SigMF recording folder.
- `[spectrum]` — FFT size, window, averaging, max/min hold, Y-axis range, grid, axis-label toggles, dark/light background, trace styling for each background.
- `[waterfall]` — intensity range, colormap (per background), grid/axis-label toggles, row count.
- `[ui]` — control-panel visibility.
- `[updates]` — `auto_check` (set to `false` to disable update notifications), plus internal book-keeping fields the program manages on its own.

Missing keys are filled in from built-in defaults on next launch. The file is rewritten on close with a header comment explaining what it is.

To reset every value to its default: use **Help → About → Restore Defaults…**, or just delete the file and launch the app.


## 8. Appendix B — Device selection and SigMF playback

### Choosing among multiple radios

The program enumerates everything supported at launch — Ettus B210s via UHD, plus any SoapySDR-recognised receiver (SDRPlay, RTL-SDR, HackRF, Airspy, Airspy HF+, BladeRF, LimeSDR, PlutoSDR). Behavior:

- **No radio attached, no playback sample:** an error dialog says "No radio found" and explains how to enable playback (see below). The app exits.
- **No radio attached, but `sample.sigmf-data` + `sample.sigmf-meta` are present next to the program:** the app falls back to **SigMF playback mode** (see below). An informational dialog announces the fallback.
- **One radio attached:** the app opens it and remembers it in `settings.ini`.
- **One B210 attached alongside other types** (e.g. B210 + RSPduo, B210 + RTL-SDR): the app silently opens the B210. The B210 is the primary supported device; other types are still reachable through the **Device** button on the sidebar.
- **Multiple B210s attached:** a picker shows the B210s; pick one. Other attached non-B210 radios are reachable through the **Device** button after launch.
- **Multiple non-B210 radios attached (no B210)**: a picker shows them all (e.g. an RSPduo and an RTL-SDR); pick one. The app remembers your choice.

If the remembered device isn't attached on a later launch, the picker re-opens.

The **RX** sidebar group has a button labeled `Device: <product> <serial>` showing which radio the current session is using. Clicking it re-opens the picker; the new choice takes effect on the next launch.

The sample-rate combo and gain-slider range adapt automatically to whichever radio is open. SDRPlay caps at 10 MHz; RTL-SDR maxes around 3.2 MHz; HackRF goes to 20 MHz; the B210 to 25 MHz. Saved gain is clamped to the new device's range if you switch to a narrower one.

To pin a specific device permanently without using the picker, edit `settings.ini` and set `device_driver` + `device_serial` under `[rx]`. Use `device_serial = auto` to restore the default "first found" behavior.

### SigMF playback mode (no-device fallback)

The distribution bundle includes a short SigMF recording so that users without a B210 can still launch the program, see live spectrum, and try the controls.

- Filenames: **`sample.sigmf-data`** (raw IQ) and **`sample.sigmf-meta`** (JSON metadata). Both live next to `b210_spectrum_analyzer.py` in your install folder.
- The file is read in a continuous loop, paced to match the original capture's sample rate.
- The window title shows **[Playback]**, the Device button shows the file name, and the Recording-status label reads `Playback (looping): sample.sigmf-data`.
- **Sample Rate**, **RX Gain**, and **Recording** controls are **disabled** — they have no meaning for a recorded file. Sample rate comes from the file's metadata.
- **Tuning IS enabled** in playback mode and works as a digital frequency shift on the file's baseband. Tuning to the file's actual center frequency (read from the .sigmf-meta) shows the recording's true content. Tuning to other frequencies within ±(sample_rate/2) of the file's center lets you explore the recorded bandwidth — useful for poking around inside the capture. Tune well outside that window and you'll see noise / wrap-around, since the recording doesn't contain data at those frequencies. This is the expected behavior for true I/Q data, not a bug.
- All visualization controls (Spectrum panel, Waterfall panel, including the dark/light background toggle, FFT averaging, max/min hold, intensity range, colormap, etc.) work normally.
- To replace the bundled sample with your own recording, do a real recording in live mode, then rename the resulting two files to `sample.sigmf-data` and `sample.sigmf-meta` and drop them next to the program. No source-code change is required.
- To skip playback mode and force an error exit when no B210 is attached, delete or rename either of the two `sample.sigmf-*` files.
