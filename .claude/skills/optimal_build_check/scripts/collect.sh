#!/usr/bin/env bash
# optimal_build_check: collect phase.
#
# Runs a fixed, cheap experiment against a Bazel build and saves every artifact
# the analyzer needs. Default is 5 builds total: a 4-point --jobs sweep
# {1, 2, 4, NCORES} (each from a clean state) plus one no-op rebuild to probe
# cache reuse. Every command is echoed and logged so the result is reproducible
# by hand.
set -euo pipefail

TARGET="//..."
MODE="full"            # full = 5 builds, quick = jobs=1 + jobs=NCORES + no-op
OUT_BASE=".optimal_build_check"
EXTRA_FLAGS=()

usage() {
  cat <<'EOF'
Usage: collect.sh [TARGET] [--quick] [--out DIR] [-- BAZEL_FLAGS...]

  TARGET        Bazel target pattern (default //...)
  --quick       fewer builds (jobs=1, jobs=NCORES, no-op)
  --out DIR     base output directory (default .optimal_build_check)
  -- FLAGS      extra flags appended to every 'bazel build'
                (e.g. -- --config=remote --config=remote_debian12_x64)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) MODE="quick"; shift ;;
    --out) OUT_BASE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; EXTRA_FLAGS=("$@"); break ;;
    -*) echo "unknown option: $1" >&2; usage; exit 1 ;;
    *) TARGET="$1"; shift ;;
  esac
done

command -v bazel >/dev/null 2>&1 || { echo "bazel not found on PATH" >&2; exit 1; }

if command -v nproc >/dev/null 2>&1; then
  NCORES="$(nproc)"
elif command -v sysctl >/dev/null 2>&1; then
  NCORES="$(sysctl -n hw.ncpu)"
else
  NCORES=4
fi

TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${OUT_BASE}/${TS}"
mkdir -p "$RUN_DIR"
CMDLOG="${RUN_DIR}/commands.log"
SWEEP="${RUN_DIR}/sweep.csv"
echo "jobs,wall_s,critical_path_s" > "$SWEEP"

# Jobs list: always includes 1 and NCORES, four distinct ascending points.
if [[ "$MODE" == "quick" ]]; then
  if [[ "$NCORES" -le 1 ]]; then JOBS_LIST=(1); else JOBS_LIST=(1 "$NCORES"); fi
else
  if [[ "$NCORES" -eq 1 || "$NCORES" -eq 2 || "$NCORES" -eq 4 ]]; then
    JOBS_LIST=(1 2 4 8)
  else
    JOBS_LIST=(1 2 4 "$NCORES")
  fi
fi

log() { echo "$*" | tee -a "$CMDLOG"; }

log "optimal_build_check collect"
log "  target: $TARGET"
log "  cores:  $NCORES"
log "  mode:   $MODE (${#JOBS_LIST[@]} clean builds + 1 no-op)"
log "  extra:  ${EXTRA_FLAGS[*]:-(none)}"
log ""

record() {
  local jobs="$1" logf="$2" line wall cp
  line="$(grep -E 'Elapsed time: .*Critical Path:' "$logf" | tail -1 || true)"
  wall="$(printf '%s' "$line" | grep -oE 'Elapsed time: [0-9.]+s' | grep -oE '[0-9.]+' | head -1 || true)"
  cp="$(printf '%s' "$line" | grep -oE 'Critical Path: [0-9.]+s' | grep -oE '[0-9.]+' | head -1 || true)"
  echo "${jobs},${wall:-NA},${cp:-NA}" >> "$SWEEP"
  log "  -> jobs=${jobs}: wall=${wall:-NA}s critical_path=${cp:-NA}s"
}

for j in "${JOBS_LIST[@]}"; do
  log "+ bazel clean"
  bazel clean >>"$CMDLOG" 2>&1
  prof="${RUN_DIR}/profile_jobs_${j}.json.gz"
  logf="${RUN_DIR}/build_jobs_${j}.log"
  bargs=(build "$TARGET" --jobs="$j" --profile="$prof")
  if [[ "$j" -eq 1 ]]; then
    bargs+=(--execution_log_json_file="${RUN_DIR}/exec_jobs_1.json")
  fi
  bargs+=(${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"})
  log "+ bazel ${bargs[*]}"
  if ! bazel "${bargs[@]}" >"$logf" 2>&1; then
    cat "$logf" >>"$CMDLOG"
    echo "build failed at jobs=$j, see $logf" >&2
    exit 1
  fi
  cat "$logf" >>"$CMDLOG"
  record "$j" "$logf"
done

# No-op rebuild from a warm cache: nothing changed, so ideally nothing re-runs.
NOOP_LOG="${RUN_DIR}/noop.log"
EXPLAIN="${RUN_DIR}/explain.txt"
nargs=(build "$TARGET" --explain="$EXPLAIN" --verbose_explanations)
nargs+=(${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"})
log "+ bazel ${nargs[*]}"
bazel "${nargs[@]}" >"$NOOP_LOG" 2>&1 || true
cat "$NOOP_LOG" >>"$CMDLOG"

# Structural fan-out: which targets, when changed, force the most rebuilding.
# A heavy leaf dominates critical-path TIME; a high fan-out node dominates
# INVALIDATION. These two queries let the analyzer report both.
log "+ bazel query 'kind(rule, ${TARGET})'"
bazel query "kind(rule, ${TARGET})" >"${RUN_DIR}/rules.txt" 2>>"$CMDLOG" || true
log "+ bazel query 'deps(${TARGET})' --output=graph --noimplicit_deps"
bazel query "deps(${TARGET})" --output=graph --noimplicit_deps \
  >"${RUN_DIR}/graph.dot" 2>>"$CMDLOG" || true

JOBS_CSV="$(IFS=,; echo "${JOBS_LIST[*]}")"
cat > "${RUN_DIR}/meta.json" <<EOF
{"target":"${TARGET}","ncores":${NCORES},"mode":"${MODE}","jobs_list":[${JOBS_CSV}],"extra_flags":"${EXTRA_FLAGS[*]:-}"}
EOF

log ""
log "collect complete: ${RUN_DIR}"
echo "$RUN_DIR"
