"""業種別の公告件数を数え、狙う業種を選ぶための調査スクリプト。"""
import collections
import datetime as dt
import json
import re
import sys
import time

from fetch import search

# 業種名: (全文検索クエリ, 件名の正規表現)
INDUSTRIES = {
    "清掃": ("清掃", r"清掃"),
    "警備": ("警備", r"警備"),
    "設備保守・点検": ("保守点検", r"保守点検|設備点検|定期点検|設備保守"),
    "イベント運営": ("イベント", r"イベント|運営業務|フェア|フェスタ"),
    "翻訳・通訳": ("翻訳", r"翻訳|通訳"),
    "印刷": ("印刷", r"印刷"),
    "測量・調査設計": ("測量", r"測量|調査設計"),
    "調査・コンサル": ("調査", r"調査業務|調査研究|実態調査|検討業務|支援業務"),
    "広報・動画・デザイン": ("広報", r"広報|動画|デザイン|PR|ＰＲ|パンフレット"),
    "Web・システム": ("システム", r"ホームページ|ウェブ|Web|WEB|システム|アプリ"),
    "給食・食品": ("給食", r"給食|食材"),
    "廃棄物処理": ("廃棄物", r"廃棄物|収集運搬"),
    "研修・講座": ("研修", r"研修|講座|セミナー"),
}


def main(days=30):
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    out = {}
    for name, (q, pat) in INDUSTRIES.items():
        rx = re.compile(pat)
        items = [it for it in search(q, since) if rx.search(it["ProjectName"])]
        uniq = {it["Key"]: it for it in items}
        orgs = collections.Counter(it["OrganizationName"] for it in uniq.values())
        prefs = collections.Counter(it["PrefectureName"] or "国" for it in uniq.values())
        out[name] = {"count": len(uniq), "orgs": len(orgs), "top_prefs": prefs.most_common(3),
                     "samples": [it["ProjectName"][:50] for it in list(uniq.values())[:5]]}
        print(f"{name}: {len(uniq)}件 / 発注機関{len(orgs)}", file=sys.stderr)
        time.sleep(1)
    json.dump(out, open(f"data/industry_scan_{dt.date.today()}.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
