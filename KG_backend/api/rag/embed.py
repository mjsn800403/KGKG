"""Stage 2: embed every page (blob) with a local multilingual model.

One vector per unique page (not per chunk). Vectors are L2-normalised, so
cosine ranking == nearest-neighbour search. For each blob we write:
  * an int8 vector into vec_blobs -> the served index (4x smaller, fast);
  * a float vector into vec_build -> used transiently to build the semantic
    graph, then dropped.
Resumable: blobs already present in vec_blobs are skipped.
"""
import time
import numpy as np

from . import config, store

_MODEL = None


def _empty_cache():
    """Release cached MPS memory between batches. Without this, bge-m3's
    transient attention buffers accumulate on Apple-Silicon GPU over a long
    embedding run -- throughput collapses and eventually it dies with an
    'Invalid buffer size' allocation error. Cheap to call; no-op off MPS."""
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


def get_model():
    """Load the embedding model once, preferring Apple-Silicon GPU (MPS), else
    CPU. On MPS the model is loaded in float16 (config.EMBED_FP16) for ~3x
    throughput and half the memory."""
    global _MODEL
    if _MODEL is None:
        import torch
        from sentence_transformers import SentenceTransformer
        device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        kwargs = {}
        if device == 'mps' and config.EMBED_FP16:
            kwargs['model_kwargs'] = {'torch_dtype': torch.float16}
        _MODEL = SentenceTransformer(config.EMBED_MODEL, device=device, **kwargs)
        # Bound the sequence length: caps the MPS attention buffer (otherwise
        # allocated for the model's 8192 max -> 4 GiB -> Metal abort) and speeds
        # up encoding. Our embed text is the page head, well under this.
        _MODEL.max_seq_length = config.MAX_SEQ_LEN
    return _MODEL


def warmup():
    """Eagerly load the model and run one tiny encode so the FIRST real query
    doesn't eat the ~10-15s cold-load + lazy-graph-build latency. Safe to call
    from a background thread at server start; swallows errors (e.g. offline
    model not present) so it can never block boot."""
    try:
        encode(['warmup'], is_query=True)
        return True
    except Exception:
        return False


def encode(texts, batch_size=32, is_query=False, progress=False):
    """Return an (N, EMBED_DIM) float32 array of L2-normalised embeddings.

    Applies the model's instruction prefix (e5 needs "query:"/"passage:";
    bge-m3 and minilm use none)."""
    model = get_model()
    prefix = config.QUERY_PREFIX if is_query else config.PASSAGE_PREFIX
    if prefix:
        texts = [prefix + t for t in texts]
    vecs = model.encode(
        texts, batch_size=batch_size, normalize_embeddings=True,
        convert_to_numpy=True, show_progress_bar=progress,
    )
    return vecs.astype(np.float32)


def _embed_text(comp_readable, text):
    """Self-describing, length-capped input for one page: the component
    breadcrumb (car-independent) followed by a body of <= EMBED_TEXT_CHARS.

    The body prefers spec/torque TABLE rows ('A | B | C', as ingest flattens
    them) that fall BELOW the prose head — capacities, torque figures and part
    numbers are the most retrieval-worthy facts and often sit past the first
    ~800 chars, where only FTS could see them. We pull a few (up to half the
    budget) ahead of the prose head so the DENSE vector can match them too. FTS
    still indexes the whole page, so nothing is lost.

    NOTE: changing this changes every passage embedding -> the vectors must be
    rebuilt (build_rag --rebuild) for the index to benefit; queries are
    unaffected (the query side does not use this)."""
    text = (text or '').strip()
    cap = config.EMBED_TEXT_CHARS
    head = text[:cap]
    extra, used = [], 0
    for ln in (l.strip() for l in text.split('\n')):
        if ' | ' in ln and ln not in head:          # a spec row past the head
            extra.append(ln)
            used += len(ln) + 1
            if used >= cap // 2:
                break
    body = ('\n'.join(extra) + '\n' + head)[:cap] if extra else head
    return f"{comp_readable}\n{body}" if comp_readable else body


def embed_index(index, batch_size=32, log=print):
    """Embed every blob (page) lacking a vector. Writes int8 to vec_blobs (the
    served index) and float to vec_build (transient, for the graph).

    Streams in blob_id order, fetching only one window of pages at a time, so
    memory stays flat no matter how large the fleet grows (500+ models). Pages
    are embedded in ascending blob_id with no skips, so vec_blobs is always a
    contiguous prefix [1..MAX]; resuming = continue from MAX(rowid). Returns the
    number of vectors written this run."""
    store.ensure_build_vec(index)
    total_blobs = index.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
    done0 = index.execute("SELECT COUNT(*) FROM vec_blobs").fetchone()[0]
    remaining = total_blobs - done0
    if remaining <= 0:
        log(f"    embeddings already complete ({done0} vectors)")
        return 0
    if done0:
        log(f"    resuming: {done0} already embedded, {remaining} to go")

    log("    loading embedding model (first load ~20-30s, then embedding starts)...")
    get_model()
    log("    model ready; embedding now (progress prints every few seconds) ...")

    # Fetch window: small enough to keep memory flat, free MPS cache often, and
    # print progress every few seconds (the cadence proven stable on this Mac).
    FETCH = max(batch_size * 8, 128)
    written, t0 = 0, time.time()
    while True:
        start = index.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_blobs").fetchone()[0]
        rows = index.execute(
            "SELECT blob_id, comp_readable, text FROM blobs WHERE blob_id > ? "
            "ORDER BY blob_id LIMIT ?", (start, FETCH)).fetchall()
        if not rows:
            break
        buf = [(r['blob_id'], _embed_text(r['comp_readable'], r['text'])) for r in rows]
        written += _encode_insert(index, buf, batch_size)
        rate = written / max(time.time() - t0, 1e-6)
        eta = (remaining - written) / rate / 60 if rate else 0
        log(f"    embedded {done0 + written}/{total_blobs}  ({rate:.1f}/s, ~{eta:.0f} min left)")
    log(f"    embedded {written} this run (done in {time.time()-t0:.0f}s)")
    return written


def _encode_insert(index, buf, batch_size):
    # progress=False keeps the log clean (a tqdm bar spams when piped to a file);
    # the frequent "embedded X/Y (rate, ETA)" lines from embed_index are the
    # human-friendly progress signal instead.
    texts = [b[1] for b in buf]
    try:
        vecs = encode(texts, batch_size=batch_size, progress=False)
    except RuntimeError:
        # transient MPS allocation failure -> free cache and retry smaller
        _empty_cache()
        vecs = encode(texts, batch_size=max(4, batch_size // 4), progress=False)
    rows = [(bid, store.pack_f32(v)) for (bid, _), v in zip(buf, vecs)]
    # int8 serving vectors (quantise in-SQL from the float32 blob)
    index.executemany(
        "INSERT INTO vec_blobs(rowid, embedding) "
        "VALUES (?, vec_quantize_int8(vec_f32(?), 'unit'))", rows)
    # full-precision copy for graph building
    index.executemany(
        "INSERT INTO vec_build(rowid, embedding) VALUES (?, vec_f32(?))", rows)
    index.commit()
    _empty_cache()
    return len(rows)
