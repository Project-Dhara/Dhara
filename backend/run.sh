set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR="${VENV_DIR:-venv}"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Creating virtualenv in ${VENV_DIR} …"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install -r requirements.txt
fi

exec "${PYTHON}" -m uvicorn main:app --reload --port "${PORT:-8000}"
