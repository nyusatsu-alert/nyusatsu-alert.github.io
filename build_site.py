"""案件ストアから公開用の静的サイト(site/)を生成する。"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import shutil
from pathlib import Path

from verticals import VERTICALS

ROOT = Path(__file__).parent
OUT = ROOT / "site"
SITE_NAME = "入札AIアラート"
BASE_URL = "https://nyusatsu-alert.github.io"
FORM_URL = ""  # 無料登録フォーム（Googleフォーム）のURL。未設定の間は「準備中」を表示
OPEN_DAYS_WITHOUT_DEADLINE = 21  # 締切不明の案件を掲載し続ける日数
e = html.escape

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e4e4e0;--accent:#0b6e4f;
--hi:#0b6e4f;--mid:#b26b00;--lo:#8a8a8f;--chip:#eef3f0;--urgent:#c0392b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141416;--card:#1d1d20;--text:#ececef;
--muted:#9d9da3;--line:#2e2e33;--accent:#4cc39a;--hi:#2f8f6c;--mid:#a8741c;--lo:#5c5c62;--chip:#23302b;--urgent:#b23a2e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.7 -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:24px 16px 60px}
header.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px}
header.top a.logo{font-weight:700;color:var(--text);text-decoration:none}
h1{font-size:22px;margin:8px 0 4px}h2{font-size:17px;margin:30px 0 10px;border-left:4px solid var(--accent);padding-left:10px}
.sub{color:var(--muted);font-size:13px}
.btn{display:inline-block;background:var(--accent);color:#fff;border-radius:8px;padding:10px 18px;
text-decoration:none;font-weight:700}.btn.off{background:var(--lo)}
.cta{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:24px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
a.card{display:block;color:var(--text);text-decoration:none}a.card:hover{border-color:var(--accent)}
.row{display:flex;gap:14px;align-items:flex-start}
.score{min-width:54px;text-align:center;border-radius:10px;padding:6px 0;color:#fff;font-weight:700;font-size:20px}
.score small{display:block;font-size:10px;font-weight:400}
.s-hi{background:var(--hi)}.s-mid{background:var(--mid)}.s-lo{background:var(--lo)}
.t{font-weight:700}.org{color:var(--muted);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{background:var(--chip);border-radius:6px;padding:2px 8px;font-size:12px}
.chip.urgent{background:var(--urgent);color:#fff}
.lbl{font-size:12px;color:var(--muted);font-weight:700}
ul{margin:4px 0 0 18px;padding:0;font-size:14px}
.ev{font-size:12px;color:var(--muted);border-left:2px solid var(--line);padding-left:8px;margin-top:8px}
a{color:var(--accent)}footer{margin-top:40px;font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:12px}
"""


def tid(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def page(title: str, body: str, desc: str, path: str, noindex: bool = False) -> str:
    robots = '<meta name="robots" content="noindex">' if noindex else ""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">{robots}
<link rel="canonical" href="{BASE_URL}/{path}"><style>{CSS}</style></head><body><div class="wrap">
<header class="top"><a class="logo" href="/">{SITE_NAME}</a>{signup_button()}</header>
{body}
<footer>出典：<a href="https://www.kkj.go.jp/">官公需情報ポータルサイト（中小企業庁）</a>の検索APIで取得した公告をAIで要約・判定しています。
判定は公告文に基づく参考情報です。参加の可否は必ず公告原文・入札説明書でご確認ください。</footer>
</div></body></html>"""


def signup_button(big: bool = False) -> str:
    label = "毎朝のアラートを無料で受け取る" if big else "無料登録"
    if FORM_URL:
        return f'<a class="btn" href="{e(FORM_URL)}" target="_blank" rel="noopener">{label}</a>'
    return f'<span class="btn off">{label}（準備中）</span>'


def parse_deadline(a: dict | None) -> dt.date | None:
    """AIが補足付きで返した場合も先頭の YYYY-MM-DD を読む。"""
    if not a or not a.get("deadline"):
        return None
    try:
        return dt.date.fromisoformat(a["deadline"][:10])
    except ValueError:
        return None


def deadline_chip(a: dict, today: dt.date) -> str:
    d = parse_deadline(a)
    if d is None:
        return '<span class="chip">締切 要確認</span>'
    days = (d - today).days
    cls = " urgent" if days <= 7 else ""
    return f'<span class="chip{cls}">締切 {d.month:02d}/{d.day:02d}（あと{days}日）</span>'


def score_box(a: dict | None) -> str:
    if not a:
        return '<div class="score s-lo">–<small>判定待ち</small></div>'
    s = a["fit_score"]
    cls = "s-hi" if s >= 70 else "s-mid" if s >= 45 else "s-lo"
    return f'<div class="score {cls}">{s}<small>適合度</small></div>'


def is_open(rec: dict, a: dict | None, today: dt.date) -> bool:
    d = parse_deadline(a)
    if d is not None:
        return d >= today
    issued = dt.date.fromisoformat(rec["CftIssueDate"][:10])
    return (today - issued).days <= OPEN_DAYS_WITHOUT_DEADLINE


def listed(rec: dict, slug: str) -> bool:
    """一覧・個別ページに載せるか（AIが対象外と判定したものは載せない）。"""
    a = rec["analysis"].get(slug, "missing")
    return a != "missing" and (a is None or a.get("relevant", False))


def tender_card(rec: dict, a: dict | None, today: dt.date) -> str:
    yen = f"上限 {a['budget_jpy'] / 10000:,.0f}万円" if a and a.get("budget_jpy") else None
    chips = [deadline_chip(a, today)] + [
        f'<span class="chip">{e(c)}</span>' for c in (a and a.get("work_type"), a and a.get("method"), yen) if c
    ]
    summary = f"<p style='margin:4px 0;font-size:14px'>{e(a['summary'])}</p>" if a else ""
    return f"""<a class="card" href="/t/{tid(rec['Key'])}.html"><div class="row">{score_box(a)}<div>
<div class="t">{e(rec['ProjectName'])}</div>
<div class="org">{e(rec['OrganizationName'])}・{e(rec['PrefectureName'] or '国')}・公告 {rec['CftIssueDate'][:10]}</div>
<div class="chips">{''.join(chips)}</div>{summary}</div></div></a>"""


def tender_page(rec: dict, today: dt.date) -> str:
    blocks = []
    for slug, a in rec["analysis"].items():
        if not listed(rec, slug):
            continue
        v = VERTICALS[slug]
        if a is None:
            blocks.append(f'<div class="card"><div class="lbl">{e(v["name"])}向けのAI判定</div><p>判定待ちです。</p></div>')
            continue
        li = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs) or "<li>記載なし</li>"
        blocks.append(f"""<div class="card"><div class="row">{score_box(a)}<div>
<div class="lbl">{e(v["name"])}向けのAI判定</div><p style="margin:2px 0">{e(a['fit_reason'])}</p></div></div>
<div class="chips">{deadline_chip(a, today)}<span class="chip">{e(a.get('method') or '方式不明')}</span>
<span class="chip">{'上限 ' + format(a['budget_jpy'] / 10000, ',.0f') + '万円' if a.get('budget_jpy') else '予算 記載なし'}</span></div>
<p>{e(a['summary'])}</p><div class="lbl">参加資格</div><ul>{li(a['requirements'])}</ul>
<div class="lbl" style="margin-top:8px">注意点</div><ul>{li(a['cautions'])}</ul>
<div class="ev">根拠：{' ／ '.join('「' + e(x) + '」' for x in a['evidence'])}</div></div>""")
    body = f"""<h1>{e(rec['ProjectName'])}</h1>
<div class="sub">{e(rec['OrganizationName'])}・{e(rec['PrefectureName'] or '国')}・公告日 {rec['CftIssueDate'][:10]}</div>
{''.join(blocks)}
<p><a href="{e(rec['ExternalDocumentURI'])}" target="_blank" rel="noopener nofollow">公告原文を開く →</a></p>
<div class="cta">こうした案件を、業種に合わせてAIが毎朝選んで届けます。<br><br>{signup_button(True)}</div>"""
    desc = f"{rec['OrganizationName']}の入札・公募「{rec['ProjectName']}」の概要、締切、参加資格をAIが要約。"
    return page(f"{rec['ProjectName']}｜{rec['OrganizationName']}｜{SITE_NAME}", body, desc, f"t/{tid(rec['Key'])}.html")


def vertical_page(slug: str, store: dict, today: dt.date) -> str:
    v = VERTICALS[slug]
    rows = [(rec, rec["analysis"][slug]) for rec in store.values()
            if listed(rec, slug) and is_open(rec, rec["analysis"][slug], today)]
    rows.sort(key=lambda x: x[0]["CftIssueDate"], reverse=True)
    rows.sort(key=lambda x: (x[1] is None, -(x[1] or {}).get("fit_score", 0)))
    hi = [r for r in rows if r[1] and r[1]["fit_score"] >= 70]
    rest = [r for r in rows if not (r[1] and r[1]["fit_score"] >= 70)]
    body = f"""<h1>{e(v['name'])}の入札・公募案件</h1>
<div class="sub">{today.isoformat()} 更新・受付中 {len(rows)}件・対象読者：{e(v['reader'])}</div>
<div class="cta">AIが公告文を読み、中小企業でも受注できそうかを0〜100点で判定しています。毎朝メールで受け取れます。<br><br>{signup_button(True)}</div>
<h2>狙い目（適合度70以上）</h2>{''.join(tender_card(r, a, today) for r, a in hi) or '<p class="sub">現在ありません</p>'}
<h2>その他の受付中案件</h2>{''.join(tender_card(r, a, today) for r, a in rest) or '<p class="sub">現在ありません</p>'}"""
    desc = f"{v['name']}向けの官公庁・自治体の入札・公募案件を毎日更新。AIが締切・予算・参加資格を要約し、受注しやすさを判定。"
    return page(f"{v['name']}の入札・公募案件一覧｜{SITE_NAME}", body, desc, f"{slug}/")


def index_page(store: dict, today: dt.date) -> str:
    cards = []
    for slug, v in VERTICALS.items():
        n = sum(1 for rec in store.values() if listed(rec, slug) and is_open(rec, rec["analysis"][slug], today))
        cards.append(f'<a class="card" href="/{slug}/"><div class="t">{e(v["name"])}</div>'
                     f'<div class="sub">受付中 {n}件 →</div></a>')
    body = f"""<h1>官公庁の入札・公募から、御社が取れそうな案件だけをAIが毎朝お届け</h1>
<p>全国の官公庁・自治体の公告をAIが読み、締切・予算・参加資格を要約。中小企業でも受注できそうかを0〜100点で判定します。</p>
<div class="grid">{''.join(cards)}</div>
<div class="cta"><b>無料でお試しいただけます</b><br>業種を選んで登録すると、毎朝メールで狙い目の案件をお届けします。<br><br>{signup_button(True)}</div>
<h2>このサービスでわかること</h2>
<ul><li>どの役所が、どんな仕事を、いつまでに募集しているか</li>
<li>予算（上限額）と、選ばれ方（企画提案か価格競争か）</li>
<li>参加に必要な資格と、注意点（地元企業限定・実績要件など）</li>
<li>AIの判定根拠として、公告文の該当箇所の引用</li></ul>"""
    return page(f"{SITE_NAME}｜官公庁の入札・公募をAIが要約・判定", body,
                "官公庁・自治体の入札・公募案件をAIが毎日要約し、中小企業でも受注できそうな案件を判定してお届けします。", "")


def build(store: dict) -> None:
    today = dt.date.today()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "t").mkdir(parents=True)
    urls = [""]
    (OUT / "index.html").write_text(index_page(store, today))
    for slug in VERTICALS:
        (OUT / slug).mkdir()
        (OUT / slug / "index.html").write_text(vertical_page(slug, store, today))
        urls.append(f"{slug}/")
    for rec in store.values():
        if any(listed(rec, s) for s in rec["analysis"]):
            path = f"t/{tid(rec['Key'])}.html"
            (OUT / path).write_text(tender_page(rec, today))
            urls.append(path)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{BASE_URL}/{u}</loc></url>" for u in urls) + "</urlset>")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")
    (OUT / ".nojekyll").write_text("")
    print(f"サイト生成: {len(urls)}ページ → {OUT}")


if __name__ == "__main__":
    build(json.loads((ROOT / "data" / "tenders.json").read_text()))
