#!/bin/sh
set -eu

PREFIX="${MINDFRESH_PREFIX:-$HOME/.mindfresh}"
SOURCE=""
REF=""
DRY_RUN=0
NO_ONBOARD=0
YES=0

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Install mindfresh into a user-owned local prefix without sudo.

Options:
  --prefix <path>       Install prefix (default: ~/.mindfresh)
  --source <path|url>   Local source path or Git URL (default: this checkout)
  --ref <git-ref>       Git ref to checkout when --source is a Git URL
  --dry-run             Print planned actions without writing files
  --no-onboard          Do not print the onboarding next-step prompt
  --yes                 Accept defaults for non-interactive use
  -h, --help            Show this help
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix)
      [ "$#" -ge 2 ] || { echo "Error: --prefix requires a path" >&2; exit 2; }
      PREFIX=$2
      shift 2
      ;;
    --source)
      [ "$#" -ge 2 ] || { echo "Error: --source requires a path or URL" >&2; exit 2; }
      SOURCE=$2
      shift 2
      ;;
    --ref)
      [ "$#" -ge 2 ] || { echo "Error: --ref requires a git ref" >&2; exit 2; }
      REF=$2
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --no-onboard)
      NO_ONBOARD=1
      shift
      ;;
    --yes)
      YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -n "$SOURCE" ] || SOURCE=$SCRIPT_DIR

case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin|Linux) ;;
  *)
    echo "Error: unsupported platform. mindfresh installer supports macOS, Linux, and WSL." >&2
    exit 2
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required. Install Python 3.9+ and rerun ./install.sh." >&2
  exit 2
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("Error: Python 3.9+ is required")
PY

is_git_source=0
case "$SOURCE" in
  http://*|https://*|git@*|ssh://*|*.git) is_git_source=1 ;;
esac

if [ -n "$REF" ] && [ "$is_git_source" -ne 1 ]; then
  echo "Error: --ref is only supported with a Git URL --source in this installer slice." >&2
  exit 2
fi

VENV="$PREFIX/venv"
BIN_DIR="$PREFIX/bin"
TMP_ROOT="${TMPDIR:-$PREFIX/tmp}"
PIP_CACHE="${PIP_CACHE_DIR:-$PREFIX/cache/pip}"
WORK_SOURCE="$SOURCE"

echo "Mindfresh installer"
echo "  prefix: $PREFIX"
echo "  source: $SOURCE"
[ -z "$REF" ] || echo "  ref: $REF"
echo "  venv: $VENV"
echo "  bin: $BIN_DIR/mindfresh"
echo "  temp: $TMP_ROOT"
echo "  pip cache: disabled (--no-cache-dir); PIP_CACHE_DIR would be $PIP_CACHE"
echo "  sudo: no"
echo "  shell profile edits: no"
echo "  daemon/background watcher: no"
[ "$YES" -eq 0 ] || echo "  choices: defaults accepted (--yes)"

if [ "$is_git_source" -eq 0 ]; then
  if [ ! -d "$WORK_SOURCE" ]; then
    echo "Error: source path does not exist or is not a directory: $WORK_SOURCE" >&2
    exit 2
  fi
  if [ ! -f "$WORK_SOURCE/pyproject.toml" ]; then
    echo "Error: source path is missing pyproject.toml: $WORK_SOURCE" >&2
    exit 2
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Would create venv: $VENV"
  echo "Would expose command: $BIN_DIR/mindfresh"
  echo "Would install package from: $WORK_SOURCE"
  echo "Dry run only: no files were written."
  exit 0
fi

mkdir -p "$BIN_DIR" "$TMP_ROOT" "$PIP_CACHE"

if [ "$is_git_source" -eq 1 ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required for Git URL sources." >&2
    exit 2
  fi
  WORK_SOURCE="$TMP_ROOT/mindfresh-source"
  rm -rf "$WORK_SOURCE"
  git clone "$SOURCE" "$WORK_SOURCE"
  if [ -n "$REF" ]; then
    git -C "$WORK_SOURCE" checkout "$REF"
  fi
fi

python3 -m venv "$VENV"
TMPDIR="$TMP_ROOT" PIP_CACHE_DIR="$PIP_CACHE" "$VENV/bin/python" -m pip install --no-cache-dir "$WORK_SOURCE"

ln -sfn "$VENV/bin/mindfresh" "$BIN_DIR/mindfresh"

"$BIN_DIR/mindfresh" --version

echo
echo "Install complete."
echo "Run mindfresh directly:"
echo "  $BIN_DIR/mindfresh --help"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo
    echo "Optional PATH setup (not edited automatically):"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

if [ "$NO_ONBOARD" -eq 1 ]; then
  echo
  echo "Onboarding suggestion skipped because --no-onboard was provided."
else
  echo
  echo "Next:"
  echo "  $BIN_DIR/mindfresh onboard"
fi

if [ "$YES" -eq 1 ]; then
  :
fi
