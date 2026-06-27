# KGtechvault — vehicle technical documentation platform

Django backend (`KG_backend/`) + Next.js frontend (`kg_frontend/`) serving
per-car factory documentation (repair manuals, parts, standard times, special
tools), plus an offline HTML parser/crawler and a RAG/diagnostic build pipeline.

## Quick start

```bash
make setup     # install backend + frontend deps
cp .env.example .env
make dev       # backend (runserver) + frontend (next dev)
```

`make help` lists all tasks. For containerized / production-like runs and the
data bootstrap, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## Documentation

Design and reference docs live in [`docs/`](docs/):

| Doc | Topic |
|-----|-------|
| [docs/architecture.md](docs/architecture.md) | System architecture |
| [docs/backend.md](docs/backend.md) · [docs/frontend.md](docs/frontend.md) | Per-tier detail |
| [docs/api-reference.md](docs/api-reference.md) | API endpoints |
| [docs/data-model.md](docs/data-model.md) · [docs/data-pipeline.md](docs/data-pipeline.md) | Data |
| [docs/assistant.md](docs/assistant.md) · [docs/RAG_GUIDE_FA.md](docs/RAG_GUIDE_FA.md) | RAG assistant |
| [docs/setup-and-run.md](docs/setup-and-run.md) · [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Setup |
| [docs/roadmap.md](docs/roadmap.md) | Roadmap |

## Status: what deploys vs what's designed

The docs describe the full vision, including a RAG assistant and diagnostic
engine. Be aware the **currently committed/deployable scope is narrower**:

**Shipped & wired** (in `KG_backend/api/urls.py`):
- Browse API — brands → years → models → node tree (`brands_list_view`, `car_view`)
- `/healthz` readiness probe
- Media serving for per-car images

**Designed but NOT wired in the committed code:**
- `/api/assist`, `/api/diagnose`, `/api/search` endpoints — **not present** in `urls.py`.
- `api/rag/config.py` and `api/rag/feedback.py` exist but are not imported by any wired view.
- The RAG/diagnostic management commands (`build_rag`, `build_diag`, `eval_rag`,
  `optimize_index`) exist only as compiled `.pyc` in
  `api/management/commands/__pycache__/` — **the `.py` sources are not in this repo**.
  `run_rag_build.sh` and `requirements-rag.txt` are kept for when the sources are restored.

Reconcile this gap (restore the command sources and wire the endpoints, or prune
the unused modules) before advertising the RAG features as deployed.
