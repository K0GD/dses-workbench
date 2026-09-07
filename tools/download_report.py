"""Daily download report for the published Spectrum Analyzer.

Pulls the gpstime Apache access log over SSH and summarizes who fetched
the app in the last N hours: zip GETs are fresh installs or updates,
manifest GETs carry the updater's User-Agent (DSES-Spectrum-Analyzer/x.y.z)
and so reveal which versions are checking in.

Exit contract for the daily scheduled task: prints "DOWNLOADS: <n>" as
the first line — n==0 means send nothing today.

Usage:  python tools/download_report.py [--hours 24]
"""
import argparse
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

SSH = ["ssh", "-i", r"C:\Users\rick\.ssh\id_ed25519_gpstime",
       "-o", "IdentitiesOnly=yes",
       "-o", rf"UserKnownHostsFile=C:\Users\rick\.ssh\known_hosts",
       "rick@gpstime.com"]
# The HTTPS vhost (aa_GPS-le-ssl.conf) logs to requests_log, NOT
# access_log (which sees only the port-80 redirect chatter). Read this
# week's log plus the most recent rotation, so a run just after the
# weekly logrotate still sees yesterday.
REMOTE = ("sudo -n sh -c 'cat $(ls -t /var/log/httpd/requests_log* "
          "| head -2 | sort -r) | grep sw_distribution/b210_sa' || true")

LOG_RE = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) (\S+)'
    r'(?: "[^"]*" "([^"]*)")?')


def parse(hours):
    out = subprocess.run(SSH + [REMOTE], capture_output=True, text=True,
                         timeout=120)
    if out.returncode != 0 and not out.stdout:
        print("DOWNLOADS: ERROR")
        print("ssh/log fetch failed:", out.stderr.strip()[:300])
        sys.exit(2)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    zips, checks = [], Counter()
    for line in out.stdout.splitlines():
        m = LOG_RE.match(line)
        if not m:
            continue
        ip, when, verb, path, status, size, ua = m.groups()
        if verb != "GET" or status not in ("200", "206"):
            continue
        try:
            t = datetime.strptime(when, "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            continue
        if t < cutoff:
            continue
        ua = ua or "-"
        if path.endswith(".zip"):
            zips.append((t, ip, path.rsplit("/", 1)[-1], ua))
        elif path.endswith("manifest.json"):
            mv = re.search(r"DSES[ -]Spectrum[ -]Analyzer/([\d.]+)", ua)
            checks[(ip, mv.group(1) if mv else ua[:40])] += 1
    return zips, checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    args = ap.parse_args()
    zips, checks = parse(args.hours)
    print(f"DOWNLOADS: {len(zips)}")
    print(f"DSES Spectrum Analyzer distribution activity, last "
          f"{args.hours:g} h (to {datetime.now():%Y-%m-%d %H:%M} local)")
    print()
    if zips:
        print("Zip downloads (fresh installs or updates):")
        for t, ip, fn, ua in zips:
            print(f"  {t:%Y-%m-%d %H:%M}Z  {ip:<16} {fn}  [{ua[:50]}]")
    else:
        print("No zip downloads.")
    print()
    if checks:
        print("Update checks (manifest fetches), by IP and app version:")
        for (ip, ver), n in sorted(checks.items()):
            print(f"  {ip:<16} version {ver:<12} x{n}")
    else:
        print("No update checks.")


if __name__ == "__main__":
    main()
