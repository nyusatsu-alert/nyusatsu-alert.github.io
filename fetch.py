"""官公需情報ポータルサイト検索APIから、業種ごとに案件を取得する。

出典: 官公需情報ポータルサイト（中小企業庁） https://www.kkj.go.jp/
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API = "https://www.kkj.go.jp/api/"
DATA = Path(__file__).parent / "data"

FIELDS = [
    "Key", "ExternalDocumentURI", "ProjectName", "Date", "PrefectureName", "CityName",
    "OrganizationName", "Certification", "CftIssueDate", "PeriodEndTime", "Category",
    "ProcedureType", "Location", "TenderSubmissionDeadline", "OpeningTendersEvent",
    "ProjectDescription",
]


def search(query: str, since: str, until: str | None = None, count: int = 1000) -> list[dict]:
    """1回の上限は1,000件。超えた場合は期間を二分割して取り直す。"""
    hits, items = _search_once(query, since, until, count)
    if hits <= count or until == since:
        return items
    start = dt.date.fromisoformat(since)
    end = dt.date.fromisoformat(until) if until else dt.date.today()
    mid = start + (end - start) // 2
    time.sleep(1)
    left = search(query, since, mid.isoformat(), count)
    time.sleep(1)
    right = search(query, (mid + dt.timedelta(days=1)).isoformat(), end.isoformat(), count)
    return left + right


# XMLとして不正な制御文字（公告文に紛れ込むことがある）
_BAD_XML_CHARS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _get_xml(url: str) -> ET.Element:
    """取得してXMLとして読む。壊れた応答は1回取り直し、それでもだめなら文字化け・不正文字を除いて読む。"""
    for attempt in range(2):
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read()
        try:
            return ET.fromstring(body)
        except ET.ParseError:
            if attempt == 0:
                time.sleep(5)
    # 文字化けしたバイト列（不正なUTF-8）は置換文字に、制御文字は削除して読む
    cleaned = _BAD_XML_CHARS.sub(b"", body).decode("utf-8", errors="replace").encode("utf-8")
    return ET.fromstring(cleaned)


def _search_once(query: str, since: str, until: str | None, count: int) -> tuple[int, list[dict]]:
    # Project_Name や Category はデータ未整備の案件が多く取りこぼすため、
    # 全文検索(Query)で広く取り、件名でローカルに絞り込む
    params = {
        "Query": query,
        "CFT_Issue_Date": f"{since}/{until or ''}",
        "Count": str(count),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    root = _get_xml(url)
    err = root.find("Error")
    if err is not None:
        raise RuntimeError(f"{query}: {err.text}")
    hits = int(root.findtext(".//SearchHits") or 0)
    items = []
    for sr in root.iter("SearchResult"):
        item = {f: (sr.findtext(f) or "").strip() for f in FIELDS}
        item["Attachments"] = [
            {"name": (a.findtext("Name") or "").strip(), "uri": (a.findtext("Uri") or "").strip()}
            for a in sr.iter("Attachment")
        ]
        item["matched_keyword"] = query
        items.append(item)
    return hits, items


def fetch_vertical(vertical: dict, days: int = 14) -> list[dict]:
    """業種の検索語で広く取得し、件名の条件で絞り込む。"""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    seen: dict[str, dict] = {}
    for q in vertical["queries"]:
        try:
            found = search(q, since)
        except (ET.ParseError, OSError) as e:
            # 1つの検索語の不調で全体を止めない（翌日の取得で取り戻せる）
            print(f"  {q}: 取得失敗のためスキップ（{e}）", file=sys.stderr)
            continue
        items = [
            it for it in found
            if vertical["title_re"].search(it["ProjectName"])
            and not vertical["exclude_re"].search(it["ProjectName"])
        ]
        for it in items:
            seen.setdefault(it["Key"], it)
        print(f"  {q}: {len(items)}件", file=sys.stderr)
        time.sleep(1)  # 公的APIへの負荷を抑える
    return list(seen.values())


if __name__ == "__main__":
    from verticals import VERTICALS

    slug = sys.argv[1]
    items = fetch_vertical(VERTICALS[slug], int(sys.argv[2]) if len(sys.argv) > 2 else 14)
    out = DATA / f"raw_{slug}_{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"{len(items)}件 → {out}", file=sys.stderr)
