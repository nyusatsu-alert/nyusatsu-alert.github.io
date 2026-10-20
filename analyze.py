"""公告文を Claude で解析し、業種ごとの読者が受注できそうかを判定する。

必要: Python 3.10+, `pip install anthropic pydantic`, ANTHROPIC_API_KEY（または ant auth login）
"""
from __future__ import annotations

from typing import List, Optional

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"
# 料金（USD / 100万トークン）: 入力, キャッシュ書き込み, キャッシュ読み込み, 出力
PRICES = {"claude-opus-5-5": (4, 5, 0.2, 20), "claude-sonnet-5-5": (2, 2.5, 0.2, 10)}

SYSTEM = """あなたは官公庁入札に詳しいアナリストです。
読み手は「{reader}」の営業担当です。
公告文を読み、その会社が「受注を検討する価値があるか」を判定してください。

判定基準:
- relevant: 読み手の会社が主契約者として請け負う業務か。物品の購入・賃貸借、工事、
  医療/理化学機器、印刷のみ、派遣、読み手の業種と無関係な業務は false。
- fit_score (0-100): relevant な案件について、小〜中規模の会社が受注できる現実性。
  全省庁統一資格のランク、地域要件、実績要件、規模（予算）、プロポーザルか価格競争か、
  「参加者確認公募」など特定事業者を想定した方式かを考慮する。relevant=false なら 0。
- 公告文に書かれていない事項は推測せず null にし、不明点は cautions に書く。
- evidence には根拠となる公告文の箇所を短く原文のまま引用する。
- deadline は「参加に必ず必要な手続きのうち最も早い期限」を YYYY-MM-DD の形式だけで書く。
  参加申請書・競争参加資格確認書類・仕様書の受領（参加の必須条件の場合）・提案書・入札書の提出期限が対象。
  任意参加の説明会の申込期限、質問の受付期限、意見招請の期限は deadline にしない（cautions に書く）。
  時刻や補足は cautions へ書く。
- summary・fit_reason は読み手向けに平易な日本語で、それぞれ2文以内。"""


class Analysis(BaseModel):
    relevant: bool
    work_type: str  # 例: 調査・分析 / 計画策定支援 / 広報・PR / Web制作・運用 / システム開発・改修
    summary: str
    budget_jpy: Optional[int]  # 上限額・予定価格（税込）。記載なしは null
    deadline: Optional[str]  # 参加申込/提出期限 YYYY-MM-DD
    method: Optional[str]  # 公募型プロポーザル / 一般競争入札 など
    requirements: List[str]
    fit_score: int
    fit_reason: str
    cautions: List[str]
    evidence: List[str]


def analyze(client: anthropic.Anthropic, item: dict, vertical: dict,
            model: str = MODEL) -> tuple[Analysis | None, anthropic.types.Usage]:
    doc = (
        f"件名: {item['ProjectName']}\n機関: {item['OrganizationName']}\n"
        f"公告日: {item['CftIssueDate'][:10]}\nカテゴリ: {item['Category'] or '不明'}\n"
        f"公告文:\n{item.get('ProjectDescription', '')[:12000]}"
    )
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        output_config={"effort": "low"},  # 定型の抽出・分類タスク
        system=[{"type": "text", "text": SYSTEM.format(reader=vertical["reader"]),
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": doc}],
        output_format=Analysis,
    )
    if response.stop_reason == "refusal":
        return None, response.usage
    return response.parsed_output, response.usage


def cost_usd(model: str, tokens: dict) -> float:
    p_in, p_cw, p_cr, p_out = PRICES[model]
    return (tokens["input"] * p_in + tokens["cache_write"] * p_cw + tokens["cache_read"] * p_cr
            + tokens["output"] * p_out) / 1_000_000
