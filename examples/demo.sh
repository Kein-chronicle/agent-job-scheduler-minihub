#!/usr/bin/env bash
cd "$(dirname "$0")/.."
run() { printf '$ %s\n' "$*"; "$@"; printf '[exit %s]\n\n' "$?"; }
tmp=.demo-tmp; rm -rf "$tmp"; mkdir "$tmp"; trap 'rm -rf "$tmp"' EXIT
hub() { printf '$ minihub %s\n' "$*"; python3 scripts/minihub.py --state "$tmp/state.json" --now "$NOW" "$@"; printf '[exit %s]\n\n' "$?"; }
NOW=2026-01-01T09:00:00+00:00
hub add-job blog 60 30
hub add-job video 120
echo "# Nothing runs unless an operator session is registered"
hub next
hub operator-start session-A
echo "# The first due job is claimed; only one job runs at a time"
hub next
NOW=2026-01-01T09:01:00+00:00
hub next
