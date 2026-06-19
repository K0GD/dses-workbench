#!/usr/bin/env python3
"""
acceptance_live_fil.py -- pin the live .fil recording path to the offline converter.

Drives the *new* live recording path (sigproc_fil.FilterbankSink) from a GNU
Radio File Source reading a retained I/Q capture, then checks the .fil it writes
against the offline iq_to_fil.py output on the same input:

  * payload (channelized data) byte-identical;
  * header identical except the rawdatafile field (just the filename).

The reference is the already-validated offline .fil. By default that is the
production lab L-band capture, whose .fil was produced by the offline converter
and folds at ~105 sigma -- so a payload match means the live path inherits that
validation exactly. Fold the resulting live .fil with fold_psr.sh to confirm the
sigma independently.

Run in the GNU Radio (base / capture) env. Example:

    python acceptance_live_fil.py \
        --iq    ~/dses-data/lab/2026-06-16/raw/lab_20260616t2017_sim-100ms-1p6_1420mhz.cf32 \
        --ref   ~/dses-data/lab/2026-06-16/fil/lab_20260616t2017_sim-100ms-1p6_1420mhz.fil \
        --out   /tmp/live_acceptance.fil \
        --nchans 2048 --samp-rate 1250000 --center-mhz 1420.0
"""

import argparse
import sys
from pathlib import Path

from gnuradio import gr, blocks

import sigproc_fil as sf


def run_live_fil(iq_path, out_path, *, nchans, samp_rate, center_mhz,
                 tstart_mjd, integrate, source_name):
    """Flowgraph: File Source (complex64) -> FilterbankSink -> out_path."""
    tb = gr.top_block("live_fil_acceptance")
    src = blocks.file_source(gr.sizeof_gr_complex, str(iq_path), repeat=False)
    sink = sf.FilterbankSink(
        out_path, nchans=nchans, samp_rate=samp_rate,
        center_freq_mhz=center_mhz, tstart_mjd=tstart_mjd,
        integrate=integrate, source_name=source_name)
    tb.connect((src, 0), (sink, 0))
    tb.run()              # blocks until the File Source hits EOF
    sink.close()          # finalize (also done in stop(), idempotent)
    return sink.nrows


def compare(out_path, ref_path):
    """Return (payload_ok, header_ok, detail) for out vs the offline reference."""
    ho = sf.read_sigproc_header(out_path)
    hr = sf.read_sigproc_header(ref_path)
    no, nr = ho["_header_bytes"], hr["_header_bytes"]
    out_bytes = Path(out_path).read_bytes()
    ref_bytes = Path(ref_path).read_bytes()
    payload_ok = out_bytes[no:] == ref_bytes[nr:]
    skip = ("rawdatafile", "_header_bytes")
    ho_cmp = {k: v for k, v in ho.items() if k not in skip}
    hr_cmp = {k: v for k, v in hr.items() if k not in skip}
    header_ok = ho_cmp == hr_cmp
    detail = {
        "out_payload_bytes": len(out_bytes) - no,
        "ref_payload_bytes": len(ref_bytes) - nr,
        "header_diffs": {k: (ho_cmp.get(k), hr_cmp.get(k))
                         for k in set(ho_cmp) | set(hr_cmp)
                         if ho_cmp.get(k) != hr_cmp.get(k)},
    }
    return payload_ok, header_ok, detail


def main():
    home = Path.home()
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--iq", type=Path,
                   default=home / "dses-data/lab/2026-06-16/raw/"
                                  "lab_20260616t2017_sim-100ms-1p6_1420mhz.cf32")
    p.add_argument("--ref", type=Path,
                   default=home / "dses-data/lab/2026-06-16/fil/"
                                  "lab_20260616t2017_sim-100ms-1p6_1420mhz.fil")
    p.add_argument("--out", type=Path, default=Path("/tmp/live_acceptance.fil"))
    p.add_argument("--nchans", type=int, default=2048)
    p.add_argument("--samp-rate", type=float, default=1_250_000.0)
    p.add_argument("--center-mhz", type=float, default=1420.0)
    p.add_argument("--tstart-mjd", type=float, default=60000.0)
    p.add_argument("--integrate", type=int, default=1)
    p.add_argument("--source-name", default="capture")
    a = p.parse_args()

    if not a.iq.is_file():
        sys.exit(f"I/Q file not found: {a.iq}")

    print(f"Live path:  {a.iq.name}  ->  {a.out}")
    print(f"Geometry:   nchans={a.nchans} samp_rate={a.samp_rate:g} "
          f"center={a.center_mhz} MHz integrate={a.integrate}")
    nrows = run_live_fil(a.iq, a.out, nchans=a.nchans, samp_rate=a.samp_rate,
                         center_mhz=a.center_mhz, tstart_mjd=a.tstart_mjd,
                         integrate=a.integrate, source_name=a.source_name)
    print(f"Live .fil written: {nrows} rows")

    if not a.ref.is_file():
        print(f"No reference .fil at {a.ref} -- skipping comparison.")
        print("Fold the live .fil with fold_psr.sh to verify sigma.")
        return 0

    payload_ok, header_ok, detail = compare(a.out, a.ref)
    print(f"Reference:  {a.ref.name}")
    print(f"  payload bytes  live={detail['out_payload_bytes']} "
          f"ref={detail['ref_payload_bytes']}")
    print(f"  payload identical: {payload_ok}")
    print(f"  header identical (excl. rawdatafile): {header_ok}")
    if detail["header_diffs"]:
        print(f"  header diffs (live, ref): {detail['header_diffs']}")
    ok = payload_ok and header_ok
    print("\nACCEPTANCE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
