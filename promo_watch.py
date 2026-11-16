#!/usr/bin/env python3
"""New PS5 Pro public announcements and deal mentions -> Telegram.

Lead alerts are NOT confirmed inventory. Google News RSS is a best-effort
public discovery source and can be delayed, incomplete, or rate limited.
"""
import base64
import monitor_window
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
# Distinct aliases are intentionally split across queries. Marketplace promotions
# may not be indexed by Google News; this is discovery, not direct stock checking.
FEEDS = [
    ("영문명 판매·재입고", '("PS5 Pro" OR "PlayStation 5 Pro") (판매 OR 재입고 OR 입고 OR 추첨 OR 응모 OR 구매)'),
    ("국문 PS5프로", '("PS5 프로" OR "PS5프로") (판매 OR 재고 OR 특가 OR 재입고 OR 선착순 OR 예약판매)'),
    ("플레이스테이션5 프로", '("플레이스테이션5 프로" OR "플레이스테이션 5 프로" OR "플레이스테이션5프로") (판매 OR 입고 OR 추첨 OR 프로모션)'),
    ("플스5 프로", '("플스5 프로" OR "플스 5 프로" OR "플스5프로" OR "플스 프로") (재고 OR 판매 OR 핫딜 OR 특가 OR 추첨)'),
    ("모델번호 CFI-7122B", '("CFI-7122B" OR "CFI 7122B") (판매 OR 입고 OR 특가 OR 예약 OR 프로모션)'),
    ("국내 마켓", '("PS5 Pro" OR "PS5 프로") (지마켓 OR G마켓 OR SSG OR 쓱 OR 이마트 OR 디지털그랩 OR 네이버 OR 네이버플러스스토어 OR 쿠팡 OR 11번가 OR 롯데온 OR 롯데하이마트)'),
    ("SSG 새 판매/특가 공지", '("PS5 Pro" OR "PS5 프로" OR "플레이스테이션 5 프로" OR "플스5 프로") (SSG OR "SSG.COM" OR 이마트몰 OR 신세계몰 OR 쓱라이브 OR 쓱) (입고 OR 재입고 OR 판매 OR 특가 OR 타임딜 OR 예약 OR 한정 OR 행사 OR 오픈)'),
    ("G마켓 공개 판매글", '("PS5 Pro" OR "PS5프로" OR "플스5 프로" OR "플레이스테이션 5 프로") (G마켓 OR 지마켓 OR Gmarket OR "G마켓 슈퍼딜") (판매 OR 재고 OR 재입고 OR 할인 OR 특가 OR 선착순 OR 추첨)'),
    ("공식·게임 전문점", '("PS5 Pro" OR "플스5 프로") (오진상사 OR 플레이샵 OR 컴퓨존 OR 겜우리 OR 겟디즈 OR 겟디스 OR get-these OR THESE OR 전자랜드)'),
    ("플레이샵 판매·재입고 예고", '("PS5 Pro" OR "PS5 프로" OR "플레이스테이션5 프로" OR "플스5 프로") ("플레이샵" OR "오진상사" OR "PlayShop") (재입고 OR 판매 OR 추첨 OR 응모 OR 선착순 OR 입고 OR 오픈 OR 예약판매)'),
    ("플레이샵 신규 상품 링크", '("PS5 Pro" OR "플레이스테이션 5 프로" OR "CFI-7122B") (site:playshop.co.kr OR site:ojinplaystation.cafe24.com)'),
    ("플레이샵 커뮤니티 판매 제보", '("PS5 Pro" OR "PS5프로" OR "플스5 프로") ("플레이샵" OR "오진상사") (site:ppomppu.co.kr OR site:quasarzone.com OR site:ruliweb.com OR site:fmkorea.com OR site:gall.dcinside.com)'),
    ("뜻밖의 특가 판매처", '("PS5 Pro" OR "플레이스테이션5 프로") (4910 OR 무신사 OR 29CM OR 오늘의집 OR 카카오톡딜 OR 톡딜 OR 트레이더스 OR 당근 OR 크림 OR KREAM OR 래플 OR 래플즈)'),
    ("국내 특가 커뮤니티", '("PS5 Pro" OR "PS5프로") (site:ppomppu.co.kr OR site:quasarzone.com OR site:ruliweb.com OR site:fmkorea.com OR site:hotdeal.zip)'),
    ("디시인사이드 판매글", '("PS5 Pro" OR "PS5프로" OR "플레이스테이션5 프로" OR "플스5 프로" OR "CFI-7122B") (site:gall.dcinside.com OR site:dcinside.com) (재고 OR 재입고 OR 핫딜 OR 특가 OR 판매 OR 한정 OR 구매)'),
    ("판매 시작·한정 수량", '("PS5 Pro" OR "플레이스테이션 5 프로") ("한정수량" OR "선착순" OR "물량" OR "재판매" OR "판매 시작" OR "판매오픈" OR "순차출고")'),
]
COMMUNITY_RSS = [
    ("뽐뿌 핫딜 직접 RSS", "https://www.ppomppu.co.kr/rss.php?id=ppomppu"),
    ("뽐뿌 오프라인 특가 직접 RSS", "https://www.ppomppu.co.kr/rss.php?id=ppomppu5"),
]
INCLUDE = re.compile(
    r"(?:\bps\s*5\s*pro\b|\bplay\s*station\s*5\s*pro\b|"
    r"ps\s*5\s*프로|플레이\s*스테이션\s*5?\s*(?:프로|pro)|"
    r"플스\s*5?\s*(?:프로|pro)|cfi[-\s]*7122b)",
    re.I,
)
EXCLUDE = re.compile(
    r"(?:\bGTA\s*(?:6|VI)\b|게임\s*타이틀|게임소프트|기프트\s*카드|포탈\s*플레이어|"
    r"울버린|듀얼센스\s*(?:단품|패드)|디스크\s*드라이브\s*(?:단품|별도)|"
    r"케이스|거치대|스탠드\s*(?:단품|별도)|충전기|보호필름|중고|리퍼|"
    r"해외\s*직구|해외배송|미국\s*정품|해외\s*정품|예약\s*게임)",
    re.I,
)
SIGNAL = re.compile(r"판매|재고|입고|구매|추첨|응모|핫딜|특가|할인|프로모션|순차출고|오픈|물량|한정수량|선착순|픽업|예약|래플|드롭|특판|구입가능|공구", re.I)

def request(url, data=None, headers=None, method=None):
    h = {"User-Agent": "Mozilla/5.0 (compatible; PS5ProPromoWatch/1.0)",
         "Accept": "application/rss+xml,application/json,text/xml"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=20) as r:
        return r.read()

def github(path, payload=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    h = {"Authorization": f"Bearer {token}",
         "Accept": "application/vnd.github+json",
         "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    return json.loads(request(f"https://api.github.com/repos/{repo}/{path}", data, h,
                              method="PUT" if payload is not None else "GET"))

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

def read_community_rss(label, url):
    """Best-effort community RSS, independently of Google News indexing."""
    root = ET.fromstring(request(url))
    count = 0
    for item in root.findall(".//channel/item"):
        title = unescape((item.findtext("title", default="") or "").strip())
        link = (item.findtext("link", default="") or "").strip()
        raw_pub = (item.findtext("pubDate", default="") or "").strip()
        if not title or not link or not raw_pub:
            continue
        if not INCLUDE.search(title) or EXCLUDE.search(title) or not SIGNAL.search(title):
            continue
        try:
            published = email.utils.parsedate_to_datetime(raw_pub).astimezone(UTC)
        except (ValueError, TypeError, IndexError):
            continue
        count += 1
        yield {"title": title, "link": link, "published": published, "source": label}
    print(f"{label}: {count} matching community posts")


def main():
    if not monitor_window.is_active_at():
        print("Watch ended at 2026-11-19 23:59 KST; no feeds or Telegram alerts")
        return
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
    community_failures = 0
    for label, url in COMMUNITY_RSS:
        try:
            for item in read_community_rss(label, url):
                if item["published"] >= threshold:
                    key = hashlib.sha256(item["link"].encode()).hexdigest()[:24]
                    if key not in seen:
                        items[key] = item
        except Exception as exc:
            community_failures += 1
            print(f"Community RSS {label} unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    if failures == len(FEEDS) and community_failures == len(COMMUNITY_RSS):
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
    # Avoid a needless GitHub commit on every 5-minute scan when nothing
    # has changed. Create baseline once, then save only on new alerts.
    if count or sha is None:
        state["seen"] = sorted(seen)[-1500:]
        state["updated_at"] = datetime.now(UTC).isoformat()
        save_state(state, sha)
    print(f"Promo discovery complete; delivered {count} new lead alert(s); failed Google News feeds: {failures}; failed community feeds: {community_failures}")

if __name__ == "__main__":
    main()
