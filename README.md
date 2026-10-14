# 入札AIアラート（Web制作・システム開発会社向け）

官公需情報ポータルサイト（中小企業庁）の検索APIから官公庁の入札・公募案件を集め、
AI（Claude）が公告文を読んで「小〜中規模の開発会社が受注できそうか」を判定し、購読者向けアラートを生成する。

## パイプライン
1. `python3 fetch.py 14` … 直近14日の案件を取得 → `data/raw_YYYY-MM-DD.json`
   - 全文検索(Query)で広く取得し、件名でローカルに絞り込む（Project_Name/Category はデータ未整備で取りこぼすため）
   - 1回1,000件の上限を超えた場合は期間を二分割して取り直す
2. `python analyze.py data/raw_YYYY-MM-DD.json` … Claude APIで判定 → `data/analyzed_YYYY-MM-DD.json`
   - Python 3.10+、`pip install anthropic pydantic`、`ANTHROPIC_API_KEY` が必要
3. `python3 render.py data/analyzed_YYYY-MM-DD.json <取得件数>` … `reports/alert_YYYY-MM-DD.html`

## 利用条件
出典（官公需情報ポータルサイト）を明記すること。APIへの負荷を抑えるため、リクエスト間に1秒の間隔を置いている。

## 現状（2026-10-14）
- 183件を取得し、23件を対象と判定。適合度70以上は5件。
- APIキーが未設定のため、初回の判定はClaudeがセッション内で同じ観点・スキーマで実施（`data/manual_analysis_2026-10-14.py`）。
