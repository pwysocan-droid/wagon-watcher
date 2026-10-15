#!/bin/zsh
# External trigger for the watch workflow. GitHub's cron trigger drops most
# scheduled runs (see .github/workflows/watch.yml); workflow_dispatch isn't
# subject to that. Run by launchd every 20 min (com.wagonwatcher.dispatch.plist).
# Uses the gh CLI's stored login; only fires while this Mac is awake.
GH=${GH:-/opt/airbnb/gh-cli-fork/bin/gh}
REPO=pwysocan-droid/wagon-watcher
echo "$(date -u +%FT%TZ) $("$GH" workflow run watch.yml -R "$REPO" 2>&1 | tail -1)"
