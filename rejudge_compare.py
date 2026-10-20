"""判定ルールの修正後に、適合度の高い案件を判定し直し、あわせて別モデルと品質を比較する。

使い方: python rejudge_compare.py [比較モデル] [再判定の件数] [比較の件数]
- 本番モデル（analyze.MODEL）の新しい判定結果は data/tenders.json に反映する。
- 比較モデルの結果は data/model_compare_YYYY-MM-DD.json に保存するだけで、サイトには使わない。
"""
from __future__ import annotations

import datetime as dt
import json
import sys

import anthropic

from analyze import MODEL, analyze, cost_usd
from pipeline import STORE
from verticals import VERTICALS


def pick(store: dict, limit: int, min_score: int = 70, days: int = 30) -> list[tuple[dict, str]]:
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = [
        (rec, slug) for rec in store.values() for slug, a in rec["analysis"].items()
        if a and a.get("relevant") and a.get("fit_score", 0) >= min_score
        and rec["CftIssueDate"][:10] >= cutoff and rec.get("ProjectDescription")
    ]
    rows.sort(key=lambda x: -x[0]["analysis"][x[1]]["fit_score"])
    return rows[:limit]


def run(client: anthropic.Anthropic, rec: dict, slug: str, model: str, tokens: dict) -> dict | None:
    try:
        result, usage = analyze(client, rec, VERTICALS[slug], model=model)
    except anthropic.APIError as e:
        print(f"判定失敗 {model} {rec['ProjectName'][:30]}: {e}", file=sys.stderr)
        return None
    tokens["input"] += usage.input_tokens
    tokens["cache_write"] += usage.cache_creation_input_tokens or 0
    tokens["cache_read"] += usage.cache_read_input_tokens or 0
    tokens["output"] += usage.output_tokens
    return result.model_dump() if result else {"relevant": False, "refused": True}


def main(compare_model: str = "claude-sonnet-5-5", n_rejudge: int = 30, n_compare: int = 20) -> None:
    store = json.loads(STORE.read_text())
    client = anthropic.Anthropic()
    targets = pick(store, n_rejudge)
    tokens = {m: {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0} for m in (MODEL, compare_model)}
    comparison = []
    for i, (rec, slug) in enumerate(targets):
        before = rec["analysis"][slug]
        new = run(client, rec, slug, MODEL, tokens[MODEL])
        if new is None:
            continue
        rec["analysis"][slug] = new
        row = {"project": rec["ProjectName"], "org": rec["OrganizationName"], "url": rec["ExternalDocumentURI"],
               "vertical": slug, "before": before, MODEL: new}
        if i < n_compare:
            row[compare_model] = run(client, rec, slug, compare_model, tokens[compare_model])
        comparison.append(row)
        print(f"{before.get('deadline')} → {new.get('deadline')}  {rec['ProjectName'][:40]}", file=sys.stderr)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1))

    costs = {m: round(cost_usd(m, t), 4) for m, t in tokens.items()}
    out = STORE.with_name(f"model_compare_{dt.date.today().isoformat()}.json")
    out.write_text(json.dumps({"costs_usd": costs, "tokens": tokens, "rows": comparison}, ensure_ascii=False, indent=1))
    log_path = STORE.with_name("usage_log.json")
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    for m, t in tokens.items():
        log.append({"date": dt.date.today().isoformat(), "analyses": len(comparison) if m == MODEL else n_compare,
                    "model": m, "purpose": "rejudge_compare", **t, "usd_estimate": costs[m]})
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    print(f"再判定 {len(comparison)}件、推定費用 {costs}", file=sys.stderr)

    from build_site import build

    build(store)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else "claude-sonnet-5-5",
         int(args[1]) if len(args) > 1 else 30, int(args[2]) if len(args) > 2 else 20)
