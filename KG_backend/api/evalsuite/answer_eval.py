"""Answer-level evaluation: hallucination, unsupported answers, LLM baseline.

Unlike the retrieval suite, this one costs money — it drives the REAL production
chat pipeline (Next.js /api/chat), which calls the paid Metis phraser. It is
run deliberately, with a call budget, never as part of the offline suite.

What is measured, and how it is grounded:

  link_hallucination_rate
      The production route already computes the exact set of hrefs that came
      out of retrieval and strips any [BUTTON] link the model invented
      (`sanitizeButtons`), reporting the count as `strippedLinks`. A response
      with strippedLinks > 0 is a caught hallucination. This is an exact count,
      not an estimate.

  numeric_fidelity
      In a service manual the dangerous hallucination is a wrong NUMBER — a
      torque value, a capacity, a voltage. Every number in the answer is checked
      against the numbers present in the retrieved context that produced it.
      A number that appears in the answer but nowhere in its own context is
      unsupported. Purely mechanical: no judge, no LLM.

  unsupported_answer_rate
      Fraction of answers that assert content while the engine reported
      grounded=false. By design the pipeline refuses instead; this measures
      whether that design holds in practice.

  refusal correctness
      Run over the verified out-of-scope gold set: did the assistant decline?

  no_rag_baseline
      The SAME questions sent to the same LLM with NO retrieved context, to
      show what a general-purpose model does on this domain. Scored on whether
      it invents specific-looking technical claims and whether it can cite a
      real page (it has no page to cite).

Authentication: the chat route requires an AI-eligible session. A short-lived
token is minted for an existing eligible account and REVOKED at the end of the
run (see `--revoke`); no password is read or changed and no account is created.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

CHAT_URL = "http://127.0.0.1:3000/api/chat"
METIS_BASE = "https://api.metisai.ir/api/v1/chat"

# Numbers that carry engineering meaning. Bare ordinals/step numbers ("1.", "2)")
# are excluded so ordinary list formatting is not counted as a claim.
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w])")
BUTTON_RE = re.compile(r'\[BUTTON\]\(\s*title="([^"]*)"\s*,\s*href="([^"]*)"\s*\)')
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _post(url, body, headers=None, timeout=180):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ask_production(question, car, brand, token, timeout=180):
    """One turn through the real production chat pipeline."""
    return _post(CHAT_URL,
                 {"message": question, "brand": brand, "car": car,
                  "history": [], "prevSources": []},
                 {"Cookie": f"kg_portal_token={token}"}, timeout)


def ask_no_rag(question, api_key, bot_id, session_cache=None, timeout=180):
    """Same LLM, no retrieved context — the 'general-purpose LLM' baseline.

    A fresh session per question, so answers cannot lean on earlier context.
    """
    hdr = {"X-Api-Key": api_key}
    sess = _post(f"{METIS_BASE}/session",
                 {"botId": bot_id, "user": {"id": "eval-norag", "name": "_"}},
                 hdr, timeout)
    out = _post(f"{METIS_BASE}/session/{sess['id']}/message",
                {"message": {"type": "USER", "content": question}}, hdr, timeout)
    return out.get("content") or ""


# ------------------------------------------------------------- measurement
def _norm_num(s):
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else ("%g" % f)


def numbers_in(text, drop_small_ints=True):
    """Engineering-meaningful numbers in `text`.

    Small integers (<= 20) are dropped by default: they are overwhelmingly step
    numbers, item counts and list markers, not specifications, and counting them
    would inflate the apparent hallucination rate.
    """
    out = set()
    for m in NUM_RE.finditer((text or "").translate(FA_DIGITS)):
        n = _norm_num(m.group(1))
        if drop_small_ints:
            try:
                if float(n) <= 20 and float(n) == int(float(n)):
                    continue
            except ValueError:
                pass
        out.add(n)
    return out


def context_text(resp, index=None):
    """The text the answer was actually grounded in.

    The `sources` array sent to the browser carries only titles and URLs — the
    page bodies stay server-side. Scoring numeric claims against `sources`
    alone would mark every real specification as unsupported. The route does
    return `topBlobs` (the blob ids behind those sources), so the true grounding
    text is fetched from the index here.
    """
    parts = []
    for s in (resp.get("sources") or []):
        for key in ("title", "title_en", "url", "app_url", "description",
                    "trigger", "name"):
            v = s.get(key)
            if isinstance(v, str):
                parts.append(v)
    blobs = [b for b in (resp.get("topBlobs") or []) if b is not None]
    if index is not None and blobs:
        qs = ",".join("?" * len(blobs))
        for (txt,) in index.execute(
                f"SELECT text FROM blobs WHERE blob_id IN ({qs})", blobs):
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def score_answer(resp, index=None, question=""):
    """Mechanical checks over one production response."""
    reply = resp.get("reply") or ""
    sources = resp.get("sources") or []
    ctx = context_text(resp, index)
    # numbers echoed back from the user's own question are not claims
    ctx_nums = numbers_in(ctx) | numbers_in(question)
    ans_nums = numbers_in(reply)
    unsupported = sorted(n for n in ans_nums if n not in ctx_nums)
    buttons = BUTTON_RE.findall(reply)
    allowed = {s.get("url") or s.get("app_url") for s in sources
               if s.get("url") or s.get("app_url")}
    # links surviving the gate must all be ours; count any that are not
    bad_links = [h for _t, h in buttons if h not in allowed]
    return {
        "grounded": bool(resp.get("grounded")),
        "degraded": bool(resp.get("degraded")),        # no-LLM fallback served
        "llm_used": bool(resp.get("llm")),
        "mode": resp.get("mode"),
        "band": (resp.get("confidence") or {}).get("band"),
        "stripped_links": int(resp.get("strippedLinks") or 0),
        "n_sources": len(sources),
        "n_buttons": len(buttons),
        "links_not_in_sources": len(bad_links),
        "n_numbers": len(ans_nums),
        "n_unsupported_numbers": len(unsupported),
        "unsupported_numbers": unsupported[:10],
        "reply_chars": len(reply),
        "reply": reply,
    }
