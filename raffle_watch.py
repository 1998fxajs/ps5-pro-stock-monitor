#!/usr/bin/env python3
"""Track the public PlayShop standalone PS5 Pro raffle board, not store stock.

Official published registration opening and a new registration round both
notify on the same check. Excludes bundled offers by block and price.
"""
import base64
import json
import os
import re
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import monitor_window
from sale_link_review import safe_public_url

KST = ZoneInfo("Asia/Seoul")
STATE_FILE = "raffle_seen.json"
URLS = [
    "https://playshop.co.kr/board/online_entry/list.html?board_no=16",
    "https://ojinplaystation.cafe24.com/board/online_entry/list.html?board_no=16",
    "https://playshop.co.kr/board/online_apply/list.html?board_no=16",
]
DIRECT_URL = URLS[0]
SINGLE = re.compile(r"PS5\s*Pro\s*콘솔\s*[-–]\s*2TB", re.I)
FIELD = re.compile(r"뱃지\s*문구")
PRICE = re.compile(r"판매가\s*[:：]?\s*([0-9,]+)\s*원?")
START = re.compile(r"응모\s*시작일시\s*[:：]?\s*(20\d\d)[./-](\d{1,2})[./-](\d{1,2})\s*(\d{1,2}):(\d{2})")
END = re.compile(r"응모\s*종료일시\s*[:：]?\s*(20\d\d)[./-](\d{1,2})[./-](\d{1,2})\s*(\d{1,2}):(\d{2})")
MAX_KRW = 1_298_000

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections=[]
        self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script","style","noscript"):
            self.skip+=1
        if tag in ("p","div","li","tr","br","h1","h2","h3"):
            self.sections.append(" ")
    def handle_data(self, data):
        if not self.skip:
            self.sections.append(data)
    def handle_endtag(self, tag):
        if tag in ("script","style","noscript") and self.skip:
            self.skip-=1

def board_text(html):
    parser=Text()
    parser.feed(html)
    return re.sub(r"\s+", " ", unescape(" ".join(parser.sections)))

def date_from_match(match):
    return datetime(*map(int, match.groups()), tzinfo=KST)

def parse_rounds(html):
    text=board_text(html)
    sections=FIELD.split(text)
    rounds={}
    for part in sections[1:]:
        price_match=PRICE.search(part)
        begin_match=START.search(part)
        end_match=END.search(part)
        # The same board also offers Wolverine/extra-controller bundles; only
        # the block for the exact standalone title and approved price is valid.
        if not all((price_match,begin_match,end_match,SINGLE.search(part))):
            continue
        # Skip sections where an alternate bundle title is included.
        # The title is located after the metadata/raffle schedule in this UI.
        title_match=SINGLE.search(part)
        prefix=part[end_match.end():title_match.start()]
        if re.search(r"PS5\s*Pro\s*콘솔\s*\+",prefix,re.I):
            continue
        price=int(price_match.group(1).replace(",",""))
        if price>MAX_KRW or price<500000:
            continue
        try:
            begin=date_from_match(begin_match)
            end=date_from_match(end_match)
        except ValueError:
            continue
        if begin>=end:
            continue
        key=f"standalone|{price}|{begin:%Y%m%d%H%M}|{end:%Y%m%d%H%M}"
        rounds[key]={"begin":begin,"end":end,"price":price}
    return rounds

def fetch_board(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PS5ProRaffleWatch/1.0)","Accept":"text/html"})
    with urllib.request.urlopen(req,timeout=14) as response:
        data=response.read(750000)
        charset=response.headers.get_content_charset() or "utf-8"
    return data.decode(charset,errors="replace")

def gh(path, data=None):
    repo=os.environ["GITHUB_REPOSITORY"]
    token=os.environ["GITHUB_TOKEN"]
    payload=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}",
        data=payload,method="PUT" if data is not None else "GET",
        headers={"Authorization":f"Bearer {token}",
                 "Accept":"application/vnd.github+json",
                 "Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=14) as response:
        return json.load(response)

def load():
    try:
        obj=gh(f"contents/{STATE_FILE}")
        return json.loads(base64.b64decode(obj["content"]).decode()),obj["sha"]
    except HTTPError as exc:
        if exc.code==404:
            return {"sent":[]},None
        raise

def store(state,sha):
    payload={"message":"chore: record official PS5 Pro raffle notices",
             "content":base64.b64encode((json.dumps(state,ensure_ascii=False,indent=2)+"\n").encode()).decode()}
    if sha:
        payload["sha"]=sha
    gh(f"contents/{STATE_FILE}",payload)

def alert(message):
    from urllib.parse import urlencode
    token=os.environ["TELEGRAM_BOT_TOKEN"]
    chat=os.environ["TELEGRAM_CHAT_ID"]
    data=urlencode({"chat_id":chat,"text":message,"disable_web_page_preview":"true"}).encode()
    req=urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",data=data,
        headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
    with urllib.request.urlopen(req,timeout=16) as response:
        result=json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram did not accept raffle notification")

def main():
    if not monitor_window.is_active_at():
        print("Official raffle monitoring expired")
        return
    found={}
    successes=0
    for url in URLS:
        if not safe_public_url(url):
            continue
        try:
            html=fetch_board(url)
            rounds=parse_rounds(html)
            print(f"Official PlayShop raffle board {url}: {len(rounds)} standalone rounds")
            if rounds:
                successes+=1
                found.update(rounds)
        except Exception as exc:
            print(f"Official PlayShop raffle board inaccessible {url}: {type(exc).__name__}: {exc}")
    if not successes:
        # Prefer explicit failure over a green workflow with no coverage.
        raise RuntimeError("No parseable current PlayShop board; raffle notices unavailable")
    state,sha=load()
    sent=set(state.get("sent",[]))
    now=datetime.now(KST)
    delivered=0
    for key,r in sorted(found.items(),key=lambda x:x[1]["begin"]):
        if r["end"]<=now:
            continue
        start,end,price=r["begin"],r["end"],r["price"]
        announced="announced:"+key
        if announced not in sent:
            alert("[PS5 Pro 2TB 단품 정가 응모 공지]\n"
                  f"PlayShop / 오진상사\n가격: {price:,}원\n"
                  f"접수 시작: {start:%Y-%m-%d %H:%M} KST\n"
                  f"접수 마감: {end:%Y-%m-%d %H:%M} KST\n"
                  f"응모 페이지: {DIRECT_URL}\n"
                  "접수 가능 여부와 참여 조건은 공식 페이지에서 확인하세요.")
            sent.add(announced)
            delivered+=1
        started="started:"+key
        if start<=now<end and started not in sent:
            alert("[PS5 Pro 2TB 정가 응모 시작 시각 도래]\n"
                  f"접수 기간: {start:%m-%d %H:%M} ~ {end:%m-%d %H:%M} KST\n"
                  f"바로 참여: {DIRECT_URL}\n"
                  "실제 접수 가능 상태를 공식 페이지에서 확인하세요.")
            sent.add(started)
            delivered+=1
    if sent!=set(state.get("sent",[])):
        state["sent"]=sorted(sent)
        store(state,sha)
    print(f"Raffle checks completed; valid current rounds={len(found)}, alerts={delivered}")

if __name__=="__main__":
    main()
