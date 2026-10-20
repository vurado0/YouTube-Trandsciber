#!/bin/sh
# A mounted volume (Fly, Railway, plain Docker) arrives owned by root and empty,
# shadowing whatever the image had at that path. Take ownership as root, then
# drop to the unprivileged user before starting anything.
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p "${WORK_DIR:-/data}"
  chown -R app:app "${WORK_DIR:-/data}"
  exec gosu app "$@"
fi

exec "$@"
