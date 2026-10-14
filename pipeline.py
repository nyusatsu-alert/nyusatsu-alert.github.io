"""毎日の処理: 業種ごとに取得 → 案件ストアに蓄積 → 未判定分をAIで判定 → サイト生成。

使い方: python pipeline.py [取得日数]
ANTHROPIC_API_KEY が無い場合はAI判定を飛ばし、取得とサイト生成だけ行う。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

from fetch import fetch_vertical
from verticals import VERTICALS

STORE = Path(__file__).parent / "data" / "tenders.json"
# 1回の実行でAI判定する上限件数（費用の上限として機能する）
MAX_ANALYSES = int(os.environ.get("MAX_ANALYSES_PER_RUN", "60"))
META = ("Key", "ExternalDocumentURI", "ProjectName", "PrefectureName", "CityName",
        "OrganizationName", "CftIssueDate", "Category", "ProcedureType")


def load_store() -> dict:
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def merge(store: dict, slug: str, items: list[dict]) -> int:
    added = 0
    today = dt.date.today().isoformat()
    for it in items:
        rec = store.get(it["Key"])
        if rec is None:
            rec = {k: it.get(k, "") for k in META}
            # 判定用に公告文を保持（容量を抑えるため先頭のみ）
            rec["ProjectDescription"] = it["ProjectDescription"][:12000]
            rec["first_seen"] = today
            rec["analysis"] = {}
            store[it["Key"]] = rec
            added += 1
        rec.setdefault("analysis", {}).setdefault(slug, None)
    return added


def analyze_pending(store: dict) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 未設定のためAI判定をスキップ", file=sys.stderr)
        return 0
    import anthropic

    from analyze import analyze

    client = anthropic.Anthropic()
    done = 0
    tokens = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    # 新しい公告から優先して判定する
    pending = sorted(
        ((rec, slug) for rec in store.values() for slug, a in rec["analysis"].items() if a is None),
        key=lambda x: x[0]["CftIssueDate"], reverse=True,
    )
    for rec, slug in pending[:MAX_ANALYSES]:
        try:
            result, usage = analyze(client, rec, VERTICALS[slug])
        except anthropic.APIError as e:
            print(f"判定失敗 {rec['ProjectName'][:30]}: {e}", file=sys.stderr)
            continue
        rec["analysis"][slug] = result.model_dump() if result else {"relevant": False, "refused": True}
        tokens["input"] += usage.input_tokens
        tokens["cache_write"] += usage.cache_creation_input_tokens or 0
        tokens["cache_read"] += usage.cache_read_input_tokens or 0
        tokens["output"] += usage.output_tokens
        done += 1
    log_usage(done, tokens)
    return done


def log_usage(done: int, tokens: dict) -> None:
    """判定件数・トークン数・推定費用を data/usage_log.json に追記する（PDCAの費用確認用）。"""
    # Claude Opus 5.5 の料金（USD / 100万トークン）。キャッシュ書き込みは入力の1.25倍
    usd = (tokens["input"] * 4 + tokens["cache_write"] * 5 + tokens["cache_read"] * 0.2
           + tokens["output"] * 20) / 1_000_000
    path = STORE.with_name("usage_log.json")
    log = json.loads(path.read_text()) if path.exists() else []
    log.append({"date": dt.date.today().isoformat(), "analyses": done, **tokens, "usd_estimate": round(usd, 4)})
    path.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    print(f"推定費用 ${usd:.3f}（{done}件）", file=sys.stderr)


def prune(store: dict, keep_days: int = 120) -> None:
    """古い案件の公告文本文を削除して容量を抑える（判定結果とメタ情報は残す）。"""
    cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    for rec in store.values():
        if rec["CftIssueDate"][:10] < cutoff:
            rec.pop("ProjectDescription", None)


def main(days: int = 14) -> None:
    store = load_store()
    for slug, v in VERTICALS.items():
        print(f"[{v['name']}]", file=sys.stderr)
        added = merge(store, slug, fetch_vertical(v, days))
        print(f"  新規 {added}件", file=sys.stderr)
    n = analyze_pending(store)
    print(f"AI判定 {n}件", file=sys.stderr)
    prune(store)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1))

    from build_site import build

    build(store)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 14)
