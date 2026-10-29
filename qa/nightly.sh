#!/usr/bin/env bash
# Nightly QA run: the suites that need real data run against the head of
# `work` on the isolated QA stack, and their outcome becomes Prometheus metrics
# so a regression pages the same way an outage does (api/alert_rules.py, _qa).
#
#   qa/nightly.sh [git-ref]        default: origin/work
#
# Steps (each recorded even when an earlier one fails):
#   1. qa/stack.sh up <sha>        production-like settings, throttles ON
#   2. qa/run_e2e.sh               browser journeys (Playwright)
#   3. qa/dast/run_zap.sh baseline passive security scan (no attack traffic)
#   4. qa/perf/run_perf.sh baseline  single-user latency against the thresholds
#   5. qa/stack.sh down            nothing is left running
#
# Results: /opt/KGKG_qa/nightly/<UTC timestamp>-<sha9>/ (kept 30 runs).
# Metrics: $TEXTFILE_DIR/kgkg_qa.prom (node-exporter textfile collector).
# Scheduled by ops/qa/kgkg-qa-nightly.timer; safe to run by hand.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${KG_QA_REPO:-/opt/KGKG_work}
OUT_ROOT=${KG_QA_NIGHTLY_DIR:-/opt/KGKG_qa/nightly}
TEXTFILE_DIR=${KG_TEXTFILE_DIR:-/var/lib/node-exporter-textfile}
REF=${1:-origin/work}
LOCK=/run/kgkg-qa-nightly.lock

exec 9>"$LOCK"
flock -n 9 || { echo "another nightly QA run is in progress" >&2; exit 3; }

git -C "$REPO" fetch -q origin || { echo "git fetch failed" >&2; exit 4; }
SHA=$(git -C "$REPO" rev-parse --verify "$REF^{commit}") || exit 4
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=$OUT_ROOT/$STAMP-${SHA:0:9}
mkdir -p "$OUT"
START=$(date -u +%s)
echo "nightly QA for ${SHA:0:9} -> $OUT"

declare -A OK
step() {  # name, command...  (records 1/0, never aborts the run)
  local name=$1; shift
  echo "== $name  [$(date -u +%T)]"
  if "$@" > "$OUT/$name.log" 2>&1; then OK[$name]=1; else OK[$name]=0; fi
  echo "   $name: $([[ ${OK[$name]} == 1 ]] && echo pass || echo FAIL)"
}

step stack "$HERE/stack.sh" up "$SHA"
if [[ ${OK[stack]} == 1 ]]; then
  step e2e "$HERE/run_e2e.sh"
  cp -r "$HERE/e2e/results" "$OUT/e2e-results" 2>/dev/null
  step dast "$HERE/dast/run_zap.sh" baseline
  cp "$HERE"/dast/results/zap-baseline.{json,md} "$OUT/" 2>/dev/null
  step perf "$HERE/perf/run_perf.sh" baseline "$OUT/perf"
else
  OK[e2e]=0; OK[dast]=0; OK[perf]=0
fi
"$HERE/stack.sh" down > "$OUT/stack-down.log" 2>&1

# Summary (machine-readable) and metrics.
python3 - "$OUT" "$SHA" "$START" "${OK[stack]}" "${OK[e2e]}" "${OK[dast]}" "${OK[perf]}" <<'PY' \
  > "$OUT/summary.json"
import json, re, sys, time
from pathlib import Path
out, sha, start, *oks = sys.argv[1:]
ok = dict(zip(('stack', 'e2e', 'dast', 'perf'), map(int, oks)))
s = {'sha': sha, 'started': int(start), 'finished': int(time.time()), 'ok': ok}
try:
    st = json.loads((Path(out) / 'e2e-results' / 'results.json').read_text())['stats']
    s['e2e'] = {'passed': st.get('expected', 0), 'failed': st.get('unexpected', 0),
                'flaky': st.get('flaky', 0), 'skipped': st.get('skipped', 0)}
except Exception:
    pass
try:
    log = (Path(out) / 'dast.log').read_text()
    m = re.search(r'FAIL-NEW: (\d+).*?WARN-NEW: (\d+).*?PASS: (\d+)', log)
    if m:
        s['dast'] = dict(zip(('fail', 'warn', 'pass'), map(int, m.groups())))
except Exception:
    pass
try:
    k = json.loads((Path(out) / 'perf' / 'k6-baseline.json').read_text())['metrics']
    s['perf_p95_ms'] = {n: round(k[f'kg_{n}_ms']['values']['p(95)'], 1)
                        for n in ('page', 'api', 'assist') if f'kg_{n}_ms' in k}
except Exception:
    pass
print(json.dumps(s, indent=1))
PY

python3 - "$OUT/summary.json" <<'PY' > "$OUT/kgkg_qa.prom"
import json, sys
s = json.load(open(sys.argv[1]))
L = ['# HELP kgkg_qa_last_run_timestamp_seconds When the nightly QA run finished.',
     '# TYPE kgkg_qa_last_run_timestamp_seconds gauge',
     f"kgkg_qa_last_run_timestamp_seconds {s['finished']}",
     '# HELP kgkg_qa_suite_ok 1 if the suite passed in the last nightly QA run.',
     '# TYPE kgkg_qa_suite_ok gauge']
L += [f'kgkg_qa_suite_ok{{suite="{k}"}} {v}' for k, v in s['ok'].items()]
L += ['# HELP kgkg_qa_run_info Commit tested by the last nightly QA run.',
      '# TYPE kgkg_qa_run_info gauge', f'kgkg_qa_run_info{{sha="{s["sha"][:9]}"}} 1']
if 'e2e' in s:
    L += ['# TYPE kgkg_qa_e2e_tests gauge']
    L += [f'kgkg_qa_e2e_tests{{result="{k}"}} {v}' for k, v in s['e2e'].items()]
if 'dast' in s:
    L += ['# TYPE kgkg_qa_dast_rules gauge']
    L += [f'kgkg_qa_dast_rules{{result="{k}"}} {v}' for k, v in s['dast'].items()]
if 'perf_p95_ms' in s:
    L += ['# TYPE kgkg_qa_perf_p95_ms gauge']
    L += [f'kgkg_qa_perf_p95_ms{{kind="{k}"}} {v}' for k, v in s['perf_p95_ms'].items()]
print('\n'.join(L))
PY
if mkdir -p "$TEXTFILE_DIR" 2>/dev/null; then
  cp "$OUT/kgkg_qa.prom" "$TEXTFILE_DIR/.kgkg_qa.prom.tmp" && chmod 644 "$TEXTFILE_DIR/.kgkg_qa.prom.tmp" \
    && mv "$TEXTFILE_DIR/.kgkg_qa.prom.tmp" "$TEXTFILE_DIR/kgkg_qa.prom"
fi

# Keep the newest 30 runs.
ls -1dt "$OUT_ROOT"/*/ 2>/dev/null | tail -n +31 | xargs -r rm -rf
cat "$OUT/summary.json"
[[ ${OK[stack]}${OK[e2e]}${OK[dast]}${OK[perf]} == 1111 ]]
