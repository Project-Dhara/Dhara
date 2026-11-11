set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR="${VENV_DIR:-venv}"
PYTHON="${VENV_DIR}/bin/python"
WORKER_PID=""

_truthy() {
  case "${1:-}" in 1|true|TRUE|yes|YES|on|ON) return 0 ;; *) return 1 ;; esac
}

_cleanup() {
  if [[ -n "${WORKER_PID}" ]] && kill -0 "${WORKER_PID}" 2>/dev/null; then
    echo "Stopping extraction worker (pid ${WORKER_PID})…"
    kill "${WORKER_PID}" 2>/dev/null || true
    wait "${WORKER_PID}" 2>/dev/null || true
  fi
}
trap _cleanup EXIT INT TERM

if [[ ! -x "${PYTHON}" ]]; then
  echo "Creating virtualenv in ${VENV_DIR} …"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install -r requirements.txt
fi

if [[ "${SKIP_DB_MIGRATIONS:-}" != "1" && "${SKIP_DB_MIGRATIONS:-}" != "true" ]]; then
  echo "Applying database migrations (alembic upgrade head)..."
  "${VENV_DIR}/bin/alembic" upgrade head
fi

# Upload routes only enqueue jobs. A worker must claim them, or they stay
# QUEUED forever. Compose runs a separate `worker` service; host runs need
# the same process unless inline mode is on.
if _truthy "${DHARA_INLINE_JOBS:-}" ; then
  echo "DHARA_INLINE_JOBS set — jobs run inside the API (no background worker)."
elif _truthy "${DHARA_SKIP_WORKER:-}" ; then
  echo "DHARA_SKIP_WORKER set — not starting job_worker (start it yourself)."
else
  echo "Starting extraction worker: ${PYTHON} -m app.workers.job_worker"
  "${PYTHON}" -m app.workers.job_worker &
  WORKER_PID=$!
fi

# Do not exec: trap must still run so the worker is stopped with the API.
"${PYTHON}" -m uvicorn main:app --reload --port "${PORT:-8000}"
