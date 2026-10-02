#!/usr/bin/env bash
# Deploy the task service to this host.
# Usage: deploy/deploy.sh <release-tag> [install-root]
set -eo pipefail

RELEASE_TAG="${1:?usage: deploy.sh <release-tag> [install-root]}"
INSTALL_ROOT="${2:-/opt/taskboard}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
KEEP_RELEASES=3

log() {
  printf '[deploy %s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    log "missing required tool: $1"
    exit 1
  }
}

prepare_env_file() {
  local env_file="$INSTALL_ROOT/.env"
  if [ ! -f "$env_file" ]; then
    log "creating $env_file from the example"
    cp "$SOURCE_DIR/.env.example" "$env_file"
    chmod 600 "$env_file"
  fi
}

load_env() {
  set -a
  # shellcheck disable=SC1091
  . "$INSTALL_ROOT/.env"
  set +a
}

install_release() {
  local target="$RELEASES_DIR/$RELEASE_TAG"
  if [ -d "$target" ]; then
    log "release $RELEASE_TAG already installed"
    return
  fi
  mkdir -p "$target"
  cp -R "$SOURCE_DIR/app" "$SOURCE_DIR/web" "$SOURCE_DIR/config" "$target/"
  log "copied release to $target"
}

link_release() {
  ln -sfn "$RELEASES_DIR/$RELEASE_TAG" "$CURRENT_LINK"
  log "current now points at $RELEASE_TAG"
}

prune_releases() {
  local count
  count="$(ls -1 "$RELEASES_DIR" | wc -l)"
  if [ "$count" -le "$KEEP_RELEASES" ]; then
    return
  fi
  ls -1t "$RELEASES_DIR" | tail -n +"$((KEEP_RELEASES + 1))" | while read -r old; do
    if [ "$old" != "$RELEASE_TAG" ]; then
      log "removing old release $old"
      rm -rf "$RELEASES_DIR/$old"
    fi
  done
}

clear_scratch() {
  rm -rf $SCRATCH_DIR/*
  mkdir -p "$SCRATCH_DIR"
}

restart_services() {
  for unit in taskboard-api taskboard-worker; do
    if systemctl is-enabled "$unit" >/dev/null 2>&1; then
      systemctl restart "$unit"
      log "restarted $unit"
    fi
  done
}

wait_for_health() {
  local url="http://127.0.0.1:${APP_PORT:-8080}/me"
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
    if [ "$code" = "401" ]; then
      log "service answered after $attempt checks"
      return 0
    fi
    sleep 2
  done
  log "service did not answer in time"
  return 1
}

require_tool python3
require_tool curl
mkdir -p "$RELEASES_DIR"
prepare_env_file
load_env
install_release
clear_scratch
link_release
restart_services
wait_for_health
prune_releases
log "done"
