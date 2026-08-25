#!/usr/bin/env bash
# Launch the task with whichever PsychoPy interpreter is available.
#
#   ./run.sh --participant sub01 --session 1
#   ./run.sh --config glm --participant sub01 --session 1
#   ./run.sh --pilot
#
# Prefers a `psychopy` importable by `python3`; otherwise falls back to the
# interpreter bundled inside the macOS PsychoPy.app.
set -euo pipefail
cd "$(dirname "$0")"

if python3 -c "import psychopy" >/dev/null 2>&1; then
  exec python3 run_experiment.py "$@"
fi

APP=/Applications/PsychoPy.app
if [[ -x "$APP/Contents/MacOS/python" ]]; then
  export PYTHONHOME="$APP/Contents/Resources"
  exec "$APP/Contents/MacOS/python" run_experiment.py "$@"
fi

echo "PsychoPy not found. Install it (pip install psychopy) or install PsychoPy.app." >&2
exit 1
