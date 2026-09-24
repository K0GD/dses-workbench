#!/usr/bin/env bash
# publish_github.sh - refresh the public GitHub mirror of this repository.
#
# The NAS bare repo (origin) stays the master. GitHub holds a read-only copy for
# the DSES group and other stations, with the private working notes (CLAUDE.md)
# removed from EVERY commit: a fresh clone of the local repo is rewritten with
# git filter-repo, then force-pushed. The rewrite is deterministic, so repeated
# runs produce the same history and the mirror's commit ids stay stable; tags
# are carried across. Same rules and mechanism as the EVE modem mirror
# (EVE_Modem/tools/publish_github.sh, 2026-09-22).
#
#   bash tools/publish_github.sh              # mirror main + tags to dses-science/dses-workbench
#   GITHUB_REPO=<owner>/<name> bash tools/publish_github.sh   # mirror to another repository
#
# Run it after pushing to origin, and as the last step of a release cut
# (Release_Workflow.md 4.9). Needs git filter-repo (pip install git-filter-repo)
# and a GitHub login (gh auth login, or a credential helper for github.com).
#
# Difference from the EVE script: this repo usually has another session's
# uncommitted work in the tree, so a dirty tree only WARNS (the --no-local clone
# copies committed history, never the working tree). What is refused is local
# main being AHEAD of origin/main - the mirror must never get ahead of the NAS.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${GITHUB_REPO:-dses-science/dses-workbench}"
URL="https://github.com/${REPO}.git"
EXCLUDE=(CLAUDE.md)                 # private working notes; add paths here if needed

if [ -n "$(git -C "$here" status --porcelain)" ]; then
    echo "note: working tree has uncommitted changes - they are NOT mirrored (committed history only)" >&2
fi
if git -C "$here" fetch -q origin main 2>/dev/null; then
    ahead="$(git -C "$here" rev-list --count origin/main..main)"
    if [ "$ahead" != "0" ]; then
        echo "local main is $ahead commit(s) ahead of origin/main - push to the NAS first" >&2
        exit 1
    fi
else
    echo "warning: origin (NAS) unreachable - mirroring local main unverified against the master" >&2
fi
if ! git -C "$here" filter-repo --version >/dev/null 2>&1; then
    echo "git filter-repo is not installed (pip install git-filter-repo)" >&2
    exit 1
fi
case "$(uname)" in
    MINGW*|MSYS*)
        # Git for Windows: use the Windows certificate store. A stale user gitconfig on
        # this machine points http.sslCAInfo at a Vivado bundle that no longer exists.
        export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.sslBackend GIT_CONFIG_VALUE_0=schannel ;;
esac
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
echo "== cloning the local repo into $work"
git clone -q --no-local "$here" "$work/mirror"
cd "$work/mirror"
args=()
for p in "${EXCLUDE[@]}"; do args+=(--path "$p"); done
echo "== removing ${EXCLUDE[*]} from every commit"
git filter-repo --quiet --invert-paths "${args[@]}"
if git log --all --name-only --format= -- "${EXCLUDE[@]}" | grep -q .; then
    echo "filter failed: excluded paths still present" >&2
    exit 1
fi
echo "== $(git rev-list --count main) commits, $(git tag | wc -l | tr -d ' ') tags after filtering"
git remote add github "$URL"
echo "== pushing to $URL"
git push -q --force github main
git push -q --force github --tags
echo "== done: https://github.com/${REPO}"
