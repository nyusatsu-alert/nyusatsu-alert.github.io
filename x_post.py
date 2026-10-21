"""X（旧Twitter）への投稿: その日の狙い目案件から投稿文の下書きを作り、承認済みのものを投稿する。

使い方:
  python x_post.py draft   … 下書きを data/x_drafts/YYYY-MM-DD.json に作る（投稿しない）
  python x_post.py post    … 当日の下書きを投稿する（X_* の認証情報が必要）
投稿はリンクなし（リンク付き投稿はAPI料金が高いため。サイトURLはプロフィールに置く）。
必要な環境変数: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from build_site import is_open, parse_deadline
from verticals import VERTICALS

DATA = Path(__file__).parent / "data"
DRAFTS = DATA / "x_drafts"
POSTED = DATA / "x_posted.json"
POSTS_PER_DAY = 3
MIN_SCORE = 70
MIN_DAYS_LEFT = 2  # 締切まで2日未満の案件は投稿しない
TAGS = {"consulting": "#調査業務", "web": "#Web制作"}
WEEKDAYS = "月火水木金土日"


def weighted_len(text: str) -> int:
    """Xの文字数カウント（日本語などは1文字=2）。上限は280。"""
    def w(c: str) -> int:
        o = ord(c)
        return 1 if o <= 0x10FF or 0x2000 <= o <= 0x200D or 0x2010 <= o <= 0x201F or 0x2032 <= o <= 0x2037 else 2
    return sum(w(c) for c in text)


def clip(text: str, budget: int) -> str:
    out = ""
    for c in text:
        if weighted_len(out + c + "…") > budget:
            return out + "…"
        out += c
    return out


def compose(rec: dict, slug: str, a: dict) -> str:
    d = parse_deadline(a)
    head = f"【{VERTICALS[slug]['name']}向け｜適合度{a['fit_score']}】"
    org = rec["OrganizationName"]
    deadline = f"締切{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"
    budget = f"上限{a['budget_jpy'] / 10000:,.0f}万円。" if a.get("budget_jpy") else ""
    tags = f"\n#入札 #公募 {TAGS[slug]}"
    fixed = f"{head}{org}\n"
    tail = f"\n{budget}{deadline}{tags}"
    body = clip(a["summary"], 280 - weighted_len(fixed + tail))
    return fixed + body + tail


def make_drafts(store: dict, today: dt.date) -> list[dict]:
    posted = set(json.loads(POSTED.read_text())) if POSTED.exists() else set()
    cands = []
    for rec in store.values():
        for slug, a in rec["analysis"].items():
            if not (a and a.get("relevant") and a.get("fit_score", 0) >= MIN_SCORE):
                continue
            d = parse_deadline(a)
            if d is None or (d - today).days < MIN_DAYS_LEFT or not is_open(rec, a, today):
                continue
            if f"{rec['Key']}|{slug}" in posted:
                continue
            cands.append((a["fit_score"], rec, slug, a))
    cands.sort(key=lambda x: -x[0])
    # 業種が偏らないよう、まず各業種の最上位を1件ずつ取り、残りを適合度順で埋める
    firsts = []
    for slug in VERTICALS:
        top = next((c for c in cands if c[2] == slug), None)
        if top:
            firsts.append(top)
    ordered = firsts + [c for c in cands if c not in firsts]
    drafts, used = [], set()
    for _, rec, slug, a in ordered:
        if rec["Key"] in used:
            continue
        used.add(rec["Key"])
        drafts.append({"id": f"{rec['Key']}|{slug}", "text": compose(rec, slug, a),
                       "source_url": rec["ExternalDocumentURI"], "deadline": a["deadline"][:10]})
        if len(drafts) == POSTS_PER_DAY:
            break
    return drafts


def oauth_header(method: str, url: str) -> str:
    """OAuth 1.0a の署名付きヘッダ（JSON本文は署名対象外）。"""
    params = {
        "oauth_consumer_key": os.environ["X_API_KEY"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": os.environ["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    q = lambda s: urllib.parse.quote(s, safe="")
    base = "&".join([method, q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(params.items())))])
    key = f"{q(os.environ['X_API_SECRET'])}&{q(os.environ['X_ACCESS_TOKEN_SECRET'])}"
    params["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(params.items()))


def post_tweet(text: str) -> str:
    url = "https://api.x.com/2/tweets"
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), method="POST",
                                 headers={"Authorization": oauth_header("POST", url),
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["data"]["id"]


def verify() -> None:
    """投稿せずに認証だけ確認する（自分のアカウント情報を1回読み取る）。"""
    url = "https://api.x.com/2/users/me"
    req = urllib.request.Request(url, headers={"Authorization": oauth_header("GET", url)})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            me = json.loads(r.read())["data"]
        print(f"認証OK: @{me['username']}（{me['name']}）", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"認証NG: HTTP {e.code} {e.read().decode()[:300]}", file=sys.stderr)
        raise SystemExit(1)


def main(mode: str) -> None:
    if mode == "verify":
        verify()
        return
    today = dt.date.today()
    path = DRAFTS / f"{today.isoformat()}.json"
    if mode == "draft":
        store = json.loads((DATA / "tenders.json").read_text())
        drafts = make_drafts(store, today)
        DRAFTS.mkdir(exist_ok=True)
        path.write_text(json.dumps(drafts, ensure_ascii=False, indent=1))
        for d in drafts:
            print(f"--- ({weighted_len(d['text'])}/280)\n{d['text']}\n", file=sys.stderr)
        return
    if not path.exists():
        print("本日の下書きがありません", file=sys.stderr)
        return
    drafts = json.loads(path.read_text())
    posted = json.loads(POSTED.read_text()) if POSTED.exists() else []
    for d in drafts:
        if d["id"] in posted or d.get("tweet_id"):
            continue
        d["tweet_id"] = post_tweet(d["text"])
        posted.append(d["id"])
        print(f"投稿しました {d['tweet_id']}", file=sys.stderr)
        time.sleep(5)
    path.write_text(json.dumps(drafts, ensure_ascii=False, indent=1))
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "draft")
