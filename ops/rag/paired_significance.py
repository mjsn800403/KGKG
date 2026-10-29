import json, random, sys
A, B = sys.argv[1], sys.argv[2]   # baseline, candidate results.json
a, b = json.load(open(A)), json.load(open(B))
sa, sb = (sys.argv[3] if len(sys.argv) > 3 else "hybrid"), (sys.argv[4] if len(sys.argv) > 4 else "hybrid")
rng = random.Random(0); out = {}
for st in ("known_item_en", "known_item_fa", "known_item_fa_rev"):
    qa = {(q["query"], q.get("car")): q["systems"][sa] for q in a[st]["per_query"]}
    qb = {(q["query"], q.get("car")): q["systems"][sb] for q in b[st]["per_query"]}
    keys = [k for k in qa if k in qb]
    out[st] = {}
    for m in ("nDCG@5", "P@1", "R@10", "MRR"):
        d = [qb[k][m] - qa[k][m] for k in keys]; n = len(d); obs = sum(d) / n
        perm = sum(abs(sum(x if rng.random() < .5 else -x for x in d) / n) >= abs(obs) - 1e-12 for _ in range(10000))
        bs = sorted(sum(rng.choice(d) for _ in range(n)) / n for _ in range(2000))
        out[st][m] = {"base": round(sum(qa[k][m] for k in keys) / n, 3), "new": round(sum(qb[k][m] for k in keys) / n, 3),
                      "delta": round(obs, 3), "ci95": [round(bs[50], 3), round(bs[1949], 3)], "p": round((perm + 1) / 10001, 4),
                      "wins": sum(x > 0 for x in d), "losses": sum(x < 0 for x in d), "n": n}
        print(st, m, out[st][m])
json.dump(out, open(sys.argv[5] if len(sys.argv) > 5 else "/root/novelty_eval/paired_out.json", "w"), indent=2)
