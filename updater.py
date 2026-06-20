"""updater.py -- in-app upgrade helper for the DSES Spectrum Analyzer.

OS-neutral core: download a release zip, verify its SHA-256 against the
published `.sha256`, extract it, and install it either OVER the current install
(in place, with a rollback backup) or as a NEW copy in a chosen folder. Pure
Python (urllib / zipfile / shutil / hashlib / pathlib) so it can be tested
without Qt or a running GUI; the Qt install dialog and the per-OS desktop-
shortcut / relaunch steps live in the app and reuse install-shortcut.* .

Safety model: the SHA-256 is checked before anything is written, and an
in-place install backs up every file it overwrites into <target>/.dses_backup/
so a mid-way failure is rolled back rather than leaving a half-updated install.
"""

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

_CHUNK = 1 << 16
_USER_AGENT = "DSES-Spectrum-Analyzer-Updater"


def download(url, dest, progress=None):
    """Stream `url` to `dest`. progress(bytes_so_far, total_or_0) if given."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    dest = Path(dest)
    with urllib.request.urlopen(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length", 0) or 0)
        got = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    return dest


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_published_sha256(sha_url):
    """Read a `<hex>  filename` .sha256 file from a URL; return the hex digest."""
    req = urllib.request.Request(sha_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode("utf-8", "replace")
    return text.split()[0].strip().lower()


def verify(zip_path, sha_url):
    """Raise ValueError unless `zip_path`'s SHA-256 matches the published one."""
    want = fetch_published_sha256(sha_url)
    got = sha256_file(zip_path).lower()
    if got != want:
        raise ValueError(f"checksum mismatch: downloaded {got}, expected {want}")
    return True


def sha256_url_for(download_url):
    """The `.sha256` sidecar URL for a release zip URL (…-<v>.zip -> …-<v>.sha256)."""
    if download_url.endswith(".zip"):
        return download_url[:-4] + ".sha256"
    return download_url + ".sha256"


def extract_release(zip_path, dest_dir):
    """Safely extract `zip_path` into `dest_dir`; return the single top-level
    folder inside it (the `dses-spectrum-analyzer-<version>/` the bundle uses).
    Rejects absolute or `..` member paths (zip-slip guard)."""
    dest_dir = Path(dest_dir)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.strip("/")]
        for n in names:
            p = Path(n)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"unsafe path in zip: {n}")
        z.extractall(dest_dir)
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) == 1:
        return dest_dir / next(iter(tops))
    return dest_dir


# Files large enough that re-copying an identical one on every patch is wasteful
# (the bundled SigMF playback sample is ~160 MB and never changes between
# releases). When the size matches, an in-place install skips it.
_SKIP_IF_SAME_OVER = 50_000_000


def install_in_place(src_dir, target_dir):
    """Copy every entry from `src_dir` over `target_dir`, backing up anything it
    overwrites into `<target_dir>/.dses_backup/`. Rolls back on any error.
    Returns the backup directory (kept so the user can discard it later)."""
    src_dir = Path(src_dir)
    target_dir = Path(target_dir)
    backup = target_dir / ".dses_backup"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)

    done = []  # (name, existed_before) for rollback
    try:
        for item in src_dir.iterdir():
            name = item.name
            dst = target_dir / name
            if (item.is_file() and dst.is_file()
                    and item.stat().st_size == dst.stat().st_size
                    and item.stat().st_size > _SKIP_IF_SAME_OVER):
                continue  # unchanged large file (the sample) — skip the churn
            existed = dst.exists()
            if existed:
                if dst.is_dir():
                    shutil.copytree(dst, backup / name)
                else:
                    shutil.copy2(dst, backup / name)
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
            done.append((name, existed))
        return backup
    except Exception:
        # Roll back everything we touched, newest first.
        for name, existed in reversed(done):
            dst = target_dir / name
            if dst.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
            elif dst.exists():
                dst.unlink()
            saved = backup / name
            if existed and saved.exists():
                if saved.is_dir():
                    shutil.copytree(saved, dst)
                else:
                    shutil.copy2(saved, dst)
        raise


def install_new_copy(src_dir, parent_dir):
    """Copy the versioned release folder `src_dir` into `parent_dir`. Returns the
    new install path. Raises FileExistsError if it's already there."""
    src_dir = Path(src_dir)
    new_dir = Path(parent_dir) / src_dir.name
    if new_dir.exists():
        raise FileExistsError(f"{new_dir} already exists")
    shutil.copytree(src_dir, new_dir)
    return new_dir
