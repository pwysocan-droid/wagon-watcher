#!/bin/zsh
# External trigger for the watch workflow. GitHub's cron trigger drops most
# scheduled runs (see .github/workflows/watch.yml); workflow_dispatch isn't
# subject to that. Run by launchd every 20 min (com.wagonwatcher.dispatch.plist).
# Uses the gh CLI's stored login; only fires while this Mac is awake.
#
# Install (launchd can't read ~/Documents without Full Disk Access, so the
# script runs from Application Support — re-copy it after editing):
#   D="$HOME/Library/Application Support/wagonwatcher"; mkdir -p "$D"
#   cp scripts/launchd/dispatch_watch.sh "$D/"
#   cp scripts/launchd/com.wagonwatcher.dispatch.plist ~/Library/LaunchAgents/
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.wagonwatcher.dispatch.plist
# Uninstall: launchctl bootout gui/$(id -u)/com.wagonwatcher.dispatch
# Log: ~/Library/Logs/wagonwatcher-dispatch.log
GH=${GH:-/opt/airbnb/gh-cli-fork/bin/gh}
REPO=pwysocan-droid/wagon-watcher
echo "$(date -u +%FT%TZ) $("$GH" workflow run watch.yml -R "$REPO" 2>&1 | tail -1)"
