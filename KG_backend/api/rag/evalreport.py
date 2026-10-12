"""Read/write the offline evaluation runs (JSON under _rag/eval/runs/).

The harness (management command eval_rag) computes a run and calls write_run();
the read-only /api/eval/report/ endpoint calls latest_report(). Kept thin and
fs-only so it never touches the index or a model.
"""
import json

from . import config

EVAL_DIR = config.RAG_DIR / 'eval'
RUNS_DIR = EVAL_DIR / 'runs'
GOLD_PATH = EVAL_DIR / 'goldset.jsonl'


def write_run(report, ts):
    """Persist one run; `ts` is supplied by the caller (e.g. a timestamp string)."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f'run_{ts}.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def list_runs():
    if not RUNS_DIR.exists():
        return []
    return sorted(RUNS_DIR.glob('run_*.json'))


def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def latest_report():
    """The newest run's aggregates + per-query rows, plus a trend across runs."""
    runs = list_runs()
    if not runs:
        return {'runs': 0, 'latest': None, 'trend': []}
    latest = _load(runs[-1])
    trend = []
    for p in runs[-20:]:
        r = _load(p)
        if r:
            trend.append({'ts': r.get('ts'), 'n': r.get('n'),
                          'aggregates': r.get('aggregates', {})})
    return {'runs': len(runs), 'latest': latest, 'trend': trend}
