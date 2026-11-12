#!/bin/sh
# Root-owned helper, the only command the devbox user may run through sudo. It takes no arguments:
# it reads the gid of the mounted docker socket itself and adds the calling user to that group.
# Refuses gid 0, so it can never grant membership of root.
set -eu
SOCK=/var/run/docker.sock
[ -S "$SOCK" ] || exit 1
GID="$(stat -c '%g' "$SOCK")"
[ "$GID" -gt 0 ] || { echo "socket is root-owned; not joining" >&2; exit 1; }
TARGET="${SUDO_USER:-}"
[ -n "$TARGET" ] && [ "$TARGET" != root ] || exit 1
GROUP="$(getent group "$GID" | cut -d: -f1)"
if [ -z "$GROUP" ]; then
    GROUP=dockerhost
    groupadd -g "$GID" "$GROUP"
fi
usermod -aG "$GROUP" "$TARGET"
