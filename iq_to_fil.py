#!/usr/bin/env python3
"""
iq_to_fil.py  --  DSES pulsar collection: complex I/Q  ->  SIGPROC .fil

Turns a stream of complex baseband samples (e.g. a SigMF .sigmf-data capture
from the B210, or a raw complex64 file) into a SIGPROC filterbank (.fil) that
PRESTO can fold, with the header tagged telescope_id = 12 so the processing
side routes it through VLA -> observatory 'c' -> Haswell.

Geometry comes straight from Ray's Pulsar Simulator II memo (DSES Memo #1):
the N210 ran at a 625 kHz sample rate and the filterbank split it into `fbsize`
channels, so tsamp = fbsize / 625000 for every documented capture.

    Setting   -p value (s)         fbsize   tsamp (s)
    1  ms     0.00102395360748        16    2.56e-5
    10 ms     0.0102395360748        128    2.048e-4
    100 ms    0.102395360748        1024    1.6384e-3
    1  s      1.02395360748         1024    1.6384e-3
    10 s      10.2395360748           16    2.56e-5

For DM = 0 (the simulator) the frequency-axis values (fch1, foff) do not affect
the fold -- there is no dispersion delay to correct -- but nchans/nbits must
match the data layout, tsamp must be exact, and tstart matters once you do TOAs.

The SIGPROC header/channelizer/writer core now lives in the shared, OS-neutral
``sigproc_fil`` module so the offline converter here, the live RFI analyzer
recording mode, and PulsarLab's engine all run the *same* validated code.
"""

import numpy as np

# Shared, validated SIGPROC core (header, channelizer, writer). Re-exported so
# existing callers that did ``from iq_to_fil import channelize_detect`` etc.
# keep working.
from sigproc_fil import (  # noqa: F401
    sigproc_header,
    read_sigproc_header,
    channelize_detect,
    write_fil,
)

# Ray's simulator / N210 sample rate, derived three ways from the memo panels.
SIM_SAMP_RATE = 625000.0  # Hz

# Per-period reference geometry from the memo (fold period in seconds, nchans).
SIM_PRESETS = {
    "1ms":   {"period": 0.00102395360748, "fbsize": 16},
    "10ms":  {"period": 0.0102395360748,  "fbsize": 128},
    "100ms": {"period": 0.102395360748,   "fbsize": 1024},
    "1s":    {"period": 1.02395360748,    "fbsize": 1024},
    "10s":   {"period": 10.2395360748,    "fbsize": 16},
}


def iq_to_fil(iq, preset, out_path, *, samp_rate=SIM_SAMP_RATE,
              center_freq_mhz=420.0, tstart_mjd=60000.0, nbits=32,
              source_name=None):
    """Top-level: complex I/Q -> .fil using a named simulator preset."""
    cfg = SIM_PRESETS[preset]
    nchans = cfg["fbsize"]
    tsamp = nchans / samp_rate
    total_bw_mhz = samp_rate / 1e6
    power = channelize_detect(np.asarray(iq, dtype=np.complex64), nchans)
    info = write_fil(out_path, power, source_name=source_name or f"sim_{preset}",
                     center_freq_mhz=center_freq_mhz, total_bw_mhz=total_bw_mhz,
                     tstart_mjd=tstart_mjd, tsamp=tsamp, nbits=nbits)
    info["preset"] = preset
    info["fold_period_s"] = cfg["period"]
    return info


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="complex I/Q -> SIGPROC .fil (telescope_id 12)")
    p.add_argument("infile", help="raw complex64 (little-endian) I/Q file")
    p.add_argument("outfile", help="output .fil")
    p.add_argument("--preset", required=True, choices=list(SIM_PRESETS))
    p.add_argument("--samp-rate", type=float, default=SIM_SAMP_RATE)
    p.add_argument("--center-freq-mhz", type=float, default=420.0)
    p.add_argument("--tstart-mjd", type=float, default=60000.0)
    p.add_argument("--nbits", type=int, default=32, choices=[8, 32])
    p.add_argument("--source", default=None)
    a = p.parse_args()
    iq = np.fromfile(a.infile, dtype=np.complex64)
    info = iq_to_fil(iq, a.preset, a.outfile, samp_rate=a.samp_rate,
                     center_freq_mhz=a.center_freq_mhz, tstart_mjd=a.tstart_mjd,
                     nbits=a.nbits, source_name=a.source)
    print(info)
    print(f"\nFold with:\n  prepfold -nsub 16 -n 512 -topo -nodmsearch "
          f"-dm 0 -p {info['fold_period_s']} -fine {a.outfile}")
