# B210: RX antenna "TX/RX" state on frontend A passes the RX2 port at only ~5 dB

Draft issue for the Ettus/UHD tracker (uhd GitHub). Measurements
2026-09-14, DSES bench, Windows 11. Reproduction script:
`tools/antenna_switch_bench.py` in this repo (any generator + one B210).

## Summary

On the USRP B210, with a single-channel RX stream on frontend **A** and
the antenna set to **TX/RX**, a signal applied to the **RX2** connector
reaches the receive chain only **4.9 dB** below the direct path — the
switch state appears half-open. The equivalent state on frontend **B**
gives the expected ~26 dB of GaAs-switch isolation. Reproduced on **two
B210 units** and on **UHD 4.8.0 and 4.9.0** (conda-forge/radioconda
builds, stock FPGA images), via gr-uhd and via the plain C++/Python API
paths; `get_antenna()` readback reports the selected port correctly and
the front-panel LEDs follow the selection.

## Method

Signal: E4438C, 1420.5 MHz CW, cabled directly (no antennas), stepped
−80 / −60 / −40 dBm plus RF-off nulls. Receiver: B210, 2 MS/s, gain 40
(also checked at 10 and 73 — no gain dependence), tuned 250 kHz below
the carrier so the carrier bin is well away from the zero-IF DC
artefact; carrier read at its expected bin only; 100×4096-point averaged
periodograms. Frontend fixed by `set_subdev_spec` before streaming; one
frontend per process.

## Results (carrier level, dB, uncalibrated; identical floors)

Signal into **A:RX2**:

| generator | ant = RX2 | ant = TX/RX | isolation |
|---|---|---|---|
| RF off | – (floor) | – (floor) | – |
| −80 dBm | +10.8 | +5.9 | 4.9 dB |
| −60 dBm | +30.9 | +25.9 | 5.0 dB |
| −40 dBm | +50.8 | +45.9 | 4.9 dB |

Signal into **A:TX/RX**:

| generator | ant = RX2 | ant = TX/RX | isolation |
|---|---|---|---|
| −80 dBm | −8.8 | +8.4 | 17.2 dB |
| −60 dBm | +11.1 | +28.6 | 17.5 dB |
| −40 dBm | +31.4 | +48.6 | 17.2 dB |

Signal into **B:RX2**:

| generator | ant = RX2 | ant = TX/RX | isolation |
|---|---|---|---|
| −80 dBm | +13.5 | −12.2 | 25.7 dB |
| −60 dBm | +33.4 | +7.7 | 25.7 dB |
| −40 dBm | +53.4 | +27.6 | 25.8 dB |

Notes: the SELECTED paths are healthy in every case (the TRX receive
path reads 2.4 dB below the RX2 direct path — its extra switch's
insertion loss); levels track the generator dB-for-dB (rules out
compression and coupling artifacts); RF-off shows nothing (rules out
ambient pickup); gain 10/40/73 give the same isolation (rules out
AD9361 input coupling); results identical through gr-uhd 3.10 and the
app-level wrapper.

## Expected vs observed

| state | expected (SPDT at 1.4 GHz) | observed |
|---|---|---|
| FE **B**, ant TX/RX, reject RX2 | ~25 dB | 25.7 dB ✔ |
| FE **A**, ant RX2, reject TX/RX | ~25 dB | 17.2 dB (low) |
| FE **A**, ant TX/RX, reject RX2 | ~25 dB | **4.9 dB** ✘ |

## Question

Is the FE-A antenna-switch control encoding for the TX/RX receive state
driving all required control lines? The constant, level- and
gain-independent ~5 dB pass-through of the unselected throw on two
units looks like a partially-driven (floating) switch control in that
one state, with the LED line (driven separately) following the
commanded selection.

Happy to run further diagnostics on request — we have the generator and
both units on a scripted bench.
