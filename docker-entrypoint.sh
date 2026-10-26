#!/bin/sh
# Container start: load the databases on first boot, start the transcode
# worker, then serve Flask with gunicorn on $PORT.
#
# The worker must share this container: the web process saves uploaded videos
# to a local temp folder and the worker reads them from there.
set -e

if [ "${AUTO_INIT_DB:-true}" = "true" ]; then
  python init_db.py
fi

if [ "${RUN_WORKER:-true}" = "true" ]; then
  (
    while true; do
      rq worker --url "${REDIS_URL:-redis://localhost:6379/0}" dc-transcode || true
      echo "RQ worker exited; restarting in 5s" >&2
      sleep 5
    done
  ) &
fi

exec gunicorn app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-600}" \
  --access-logfile - \
  --error-logfile -
