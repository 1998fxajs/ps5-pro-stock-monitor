#!/usr/bin/env python3
"""New PS5 Pro public announcements and deal mentions -> Telegram.

Lead alerts are NOT confirmed inventory. Google News RSS is a best-effort
public discovery source and can be delayed, incomplete, or rate limited.
"""
import base64
import email.utils
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.error import HTTPError

STATE_FILE = "promo_seen.json"
KST = timezone(timedelta(hours=9))
UTC = timezone.utc
MAX_AGE_HOURS = 3
INITIAL_AGE_MINUTES = 30
FEEDS = [
    ("판매 예고", '"PS5 Pro" (판매 OR 재입고 OR 입고 OR 추첨 OR 응모)'),
    ("국내 판매처", '"PS5 프로" (겟디즈 OR 겜우리 OR 플레이샵 OR 이마트 OR SSG OR 지마켓 OR 네이버 OR 디지털그랩 OR 래플즈 OR 오진상사)'),
    ("특가", '"PS5 Pro" (핫딜 OR 특가 OR 프로모션 OR 할인 OR 판매)'),
    ("커뮤니티 특가", '"PS5 Pro" (site:ppomppu.co.kr OR site:quasarzone.com OR site:ruliweb.com OR site:fmkorea.com)'),
]
INCLUDE = re.compile(r"(?:\bps\s*5\s*pro\b|\bps5\s*프로\b|플레이스테이션\s*5?\s*프로|플스\s*5?\s*프로)", re.I)
EXCLUDE = re.compile(
    r"(?:\bGTA\s*(?:6|VI)\b|게임\s*타이틀|게임소프트|기프트\s*카드|포탈\s*플레이어|"
    r"울버린|듀얼센스\s*(?:단품|패드)|디스크\s*드라이브\s*(?:단품|별도)|"
    r"케이스|거치대|스탠드\s*(?:단품|별도)|충전기|보호필름|중고|리퍼|"
    r"해외\s*직구|해외배송|미국\s*정품|해외\s*정품|예약\s*게임)",
    re.I,
)
SIGNAL = re.compile(r"판매|재고|입고|구매|추첨|응모|핫딜|특가|할인|프로모션|순차출고|오픈|물량", re.I)

def request(url, data=None, headers=None):
    h = {"User-Agent": "Mozilla/5.0 (compatible; PS5ProPromoWatch/1.0)",
         "Accept": "application/rss+xml,application/json,text/xml"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=20) as r:
        return r.read()

def github(path, payload=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    h = {"Authorization": f"Bearer {token}",
         "Accept": "application/vnd.github+json",
         "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    return json.loads(request(f"https://api.github.com/repos/{repo}/{path}", data, h))

def load_state():
    try:
        obj = github(f"contents/{STATE_FILE}")
        return json.loads(base64.b64decode(obj["content"]).decode()), obj["sha"]
    except HTTPError as e:
        if e.code == 404:
            return {"seen": []}, None
        raise

def save_state(state, sha):
    data = {"message": "chore: update promo lead deduplication",
            "content": base64.b64encode((json.dumps(state, ensure_ascii=False) + "\n").encode()).decode()}
    if sha:
        data["sha"] = sha
    github(f"contents/{STATE_FILE}", data)

def telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    data = urllib.parse.urlencode({"chat_id": chat, "text": message,
                                   "disable_web_page_preview": "true"}).encode()
    result = json.loads(request(f"https://api.telegram.org/bot{token}/sendMessage", data,
                                {"Content-Type": "application/x-www-form-urlencoded"}))
    if result.get("ok") is not True:
        raise RuntimeError("Telegram did not confirm delivery")

def read_feed(label, query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    content = request(url)
    root = ET.fromstring(content)
    count = 0
    for item in root.findall(".//channel/item"):
        title = unescape("".join(item.findtext("title", default="")).strip())
        link = item.findtext("link", default="").strip()
        raw_pub = item.findtext("pubDate", default="")
        if not title or not link or not raw_pub:
            continue
        try:
            published = email.utils.parsedate_to_datetime(raw_pub).astimezone(UTC)
        except (ValueError, TypeError, IndexError):
            continue
        if not INCLUDE.search(title) or EXCLUDE.search(title) or not SIGNAL.search(title):
            continue
        count += 1
        yield {"title": title, "link": link, "published": published, "source": label}
    print(f"{label}: {count} matching headlines")

def main():
    state, sha = load_state()
    seen = set(state.get("seen", []))
    first_run = sha is None
    threshold = datetime.now(UTC) - timedelta(
        minutes=INITIAL_AGE_MINUTES if first_run else MAX_AGE_HOURS)
    items = {}
    failures = 0
    for label, query in FEEDS:
        try:
            for item in read_feed(label, query):
                if item["published"] >= threshold:
                    key = hashlib.sha256(item["link"].encode()).hexdigest()[:24]
                    if key not in seen:
                        items[key] = item
        except Exception as exc:
            failures += 1
            print(f"Feed {label} unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    if failures == len(FEEDS):
        raise RuntimeError("All public discovery feeds failed; no coverage")

    count = 0
    for key, item in sorted(items.items(), key=lambda kv: kv[1]["published"]):
        # An explicit LEAD message: not stock confirmation or automatic purchase.
        telegram(
            "[PS5 Pro 판매 정보 확인 필요]\n"
            f"출처 분류: {item['source']}\n"
            f"제목: {item['title']}\n"
            f"게시시각: {item['published'].astimezone(KST):%m-%d %H:%M} KST\n"
            f"링크: {item['link']}\n\n"
            "이 알림은 구매 가능한 재고를 검증한 것이 아닙니다. "
            "본체 단품/실제 가격/판매 시각을 직접 확인하세요."
        )
        seen.add(key)
        count += 1
    # Store only recent keys to avoid growing forever; keep bounded history.
    state["seen"] = sorted(seen)[-1500:]
    state["updated_at"] = datetime.now(UTC).isoformat()
    save_state(state, sha)
    print(f"Promo discovery complete; delivered {count} new lead alert(s); failed feeds: {failures}")

if __name__ == "__main__":
    main()
