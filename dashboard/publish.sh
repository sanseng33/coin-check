#!/bin/bash
# publish.sh  [desk] push dashboard/site to GitHub Pages: a generated, single-commit gh-pages branch,
# force-pushed (history stays one commit). Runs from scheduler.py after each export when publish.conf exists.
# Only pushes when data.json changed in substance (ignoring timestamps), or every HEARTBEAT_MIN minutes.
# dashboard/CNAME (optional, one line: your domain) is published too. DRY_RUN=1 = build locally, no push.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/publish.conf"
: "${GITHUB_REPO:?}" "${PAGES_BRANCH:=gh-pages}" "${HEARTBEAT_MIN:=60}"
[ "${DRY_RUN:-0}" = 1 ] || : "${GITHUB_TOKEN:?GITHUB_TOKEN not in environment}"
REPO="${PUBLISH_REPO:-$HERE/.publish_repo}"
STATE="$HERE/.publish_state"; mkdir -p "$STATE"

# fingerprint without the fields that change every run
FP=$(python3 - "$HERE/site/data.json" <<'PY'
import json, sys, hashlib
d = json.load(open(sys.argv[1]))
for k in ("generated_at", "generated_epoch"): d.pop(k, None)
for k in list(d.get("scheduler", {})):
    if k.endswith("age_min"): d["scheduler"].pop(k)
for p in d.get("positions", []): p.pop("held_hours", None); p.get("rules", {}).pop("time_stop_in_hours", None)
print(hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest())
PY
)
FP="$FP-$( { cat "$HERE/site/index.html"; cat "$HERE/CNAME" 2>/dev/null || true; } | sha256sum | cut -c1-16)"
LAST_FP=$(cat "$STATE/fp" 2>/dev/null || true); LAST_T=$(cat "$STATE/time" 2>/dev/null || echo 0)
if [ "$FP" = "$LAST_FP" ] && [ $(( $(date +%s) - LAST_T )) -lt $(( HEARTBEAT_MIN * 60 )) ]; then
  echo "no change"; exit 0
fi

if [ ! -d "$REPO/.git" ]; then
  git init -q -b "$PAGES_BRANCH" "$REPO"
  git -C "$REPO" remote add origin "https://github.com/$GITHUB_REPO.git"   # no credentials in the URL
  git -C "$REPO" config user.name "rug-desk-bot"
  git -C "$REPO" config user.email "rug-desk-bot@users.noreply.github.com"
fi
cd "$REPO"
git rm -rq --cached . 2>/dev/null || true
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp "$HERE/site/index.html" "$HERE/site/data.json" .
touch .nojekyll
if [ -f "$HERE/CNAME" ]; then cp "$HERE/CNAME" CNAME; fi
git checkout -q --orphan _next
git add -A
git commit -q -m "dashboard $(date '+%Y-%m-%d %H:%M') UTC+8"
git branch -D -q "$PAGES_BRANCH" 2>/dev/null || true
git branch -m "$PAGES_BRANCH"
git reflog expire --expire=now --all && git gc -q --prune=now

if [ "${DRY_RUN:-0}" = 1 ]; then echo "dry run: built $(git rev-parse --short HEAD), not pushed"; exit 0; fi

# token only in this process's env, handed to git via GIT_CONFIG_* env vars (not argv, not .git/config)
AUTH=$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)
GIT_TERMINAL_PROMPT=0 GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0="http.https://github.com/.extraHeader" \
  GIT_CONFIG_VALUE_0="Authorization: Basic $AUTH" \
  git push -q -f origin "$PAGES_BRANCH"
unset AUTH
echo "$FP" > "$STATE/fp"; date +%s > "$STATE/time"
echo "pushed $PAGES_BRANCH $(git rev-parse --short HEAD)"
