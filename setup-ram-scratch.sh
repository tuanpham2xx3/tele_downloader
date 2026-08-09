#!/usr/bin/env bash
set -euo pipefail

TARGET="${GETURL_RAM_SCRATCH_ROOT:-/mnt/geturl-ram}"
SIZE="${GETURL_RAM_SCRATCH_SIZE:-4G}"

if ! mountpoint -q "$TARGET" 2>/dev/null; then
    sudo -n mkdir -p "$TARGET"
    sudo -n mount -t tmpfs -o "size=$SIZE,mode=0770,uid=$(id -u),gid=$(id -g),nosuid,nodev" \
        geturl-ram "$TARGET"
fi

mkdir -p "$TARGET/extract"
echo "RAM scratch ready: $TARGET ($(df -h "$TARGET" | tail -1 | awk '{print $2}'))"
