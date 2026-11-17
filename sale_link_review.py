#!/usr/bin/env python3
"""Review public PS5 Pro sale posts and extract actionable purchase/entry links.

The result is a *lead*, not verified checkout inventory. No login or payment.
"""
import ipaddress
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from datetime import datetime
from zoneinfo import ZoneInfo
import monitor_window

KST = ZoneInfo("Asia/Seoul")
PRODUCT = re.compile(r"(?:\bps\s*5\s*pro\b|play\s*station\s*5\s*pro|ps\s*5\s*프로|플레이\s*스테이션\s*5?\s*프로|플스\s*5?\s*프로|CFI[-\s]*7122B)", re.I)
PLATFORM = re.compile(r"플스|플레이\s*스테이션|플\s*5|ps\s*5|play\s*station|cfi[-\s]*7[01]22", re.I)
RETAILER = re.compile(r"쿠팡|coupang|네이버|지마켓|G마켓|SSG|쓱|이마트|컴퓨존|겜우리|겟디즈|플레이샵|오진|11번가|하이마트|롯데온", re.I)
with Path(__file__).with_name('community_language.json').open(encoding='utf-8') as f:
    COMMUNITY_LANGUAGE = json.load(f)
COMMUNITY_CUES = re.compile('|'.join(re.escape(t) for t in COMMUNITY_LANGUAGE['observed_terms'] + COMMUNITY_LANGUAGE['user_requested_link_terms'] if t not in ('프로', '듀센', '인질셋')), re.I)
REOPENED = re.compile(r"재입고|재판매|다시|또\s*풀|지금.*(?:됨|된다|가능)|품절\s*해제", re.I)
NEGATIVE = re.compile(r"안\s*풀|안\s*뜨|재고\s*없|구매\s*불가|결제\s*(?:안|불가)|다\s*팔렸|완판|매진", re.I)
SALE = re.compile(r"응모|추첨|판매|재입고|입고|재고|구매|구입|주문|결제|매물|특가|핫딜|예약|한정|선착순|드롭|오픈|링크|주소|좌표", re.I)
CLOSED_TITLE = re.compile(r"(?:품절(?:됨|입니다|상태)?|응모\s*마감|판매\s*종료|판매\s*취소|매진|완판|SOLD\s*OUT|사기\s*주의|구매\s*불가)", re.I)
BAD_GOODS = re.compile(r"울버린|듀얼센스\s*(?:추가|번들|세트)|(?:디스크\s*드라이브|컨트롤러)\s*(?:단품|세트)|중고|리퍼|해외직구|보호필름", re.I)
DATE = re.compile(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:\s*(\d{1,2}):(\d{2}))?")
DATE_END = re.compile(r"(?:응모\s*(?:마감|종료)|신청\s*(?:마감|종료)|접수\s*(?:마감|종료)|판매\s*종료)\s*(?:일시|기간)?\s*[:：]?\s*"+DATE.pattern, re.I)
PRICE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3}){2}|\d{7})\s*원")
ACTION_WORD = re.compile(r"응모|추첨|신청|구매|판매|바로가기|상품|참여|구입|보러가기|예약|링크|주소|좌표|url", re.I)
PATH_GOOD = re.compile(r"/(?:product|item|goods|shop|store|event|raffle|apply|entry|deal|products?)/|itemview|itemdtl|product_no=|productno=|goodscode=|board_no=|/board/online|/buy\?|link\.coupang\.com/|naver\.me/", re.I)
PATH_BAD = re.compile(r"login|signup|register|cart|privacy|terms|share|facebook|twitter|instagram|youtube|review", re.I)
PRICE_CEILING = 1_380_000

class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []
        self.link = None
        self.skip = 0
        self.images = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script","style","noscript"):
            self.skip += 1
        if tag == "a":
            self.link = {"href":a.get("href",""), "text":[]}
        if tag == 'img' and not self.skip:
            self.images.append(a.get('data-original') or a.get('data-src') or a.get('src', ''))
        if tag in ("p","div","li","tr","h1","h2","h3","br"):
            self.text.append(" ")
    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)
            if self.link is not None:
                self.link["text"].append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            self.links.append((self.link["href"], " ".join(self.link["text"])))
            self.link = None
        if tag in ("script","style","noscript") and self.skip:
            self.skip -= 1

class PostBody(HTMLParser):
    """Extract DC's actual post; exclude surrounding threads and affiliate ads."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            if self.depth:
                self.depth += 1
            elif 'write_div' in dict(attrs).get('class', '').split():
                self.depth = 1
        if self.depth:
            self.parts.append(self.get_starttag_text())
    def handle_startendtag(self, tag, attrs):
        if self.depth:
            self.parts.append(self.get_starttag_text())
    def handle_endtag(self, tag):
        if self.depth:
            self.parts.append('</'+tag+'>')
            if tag == 'div':
                self.depth -= 1
    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)
    def handle_entityref(self, name):
        if self.depth:
            self.parts.append('&'+name+';')
    def handle_charref(self, name):
        if self.depth:
            self.parts.append('&#'+name+';')

def is_ps_board(url):
    u = urllib.parse.urlparse(url)
    return u.hostname == 'gall.dcinside.com' and urllib.parse.parse_qs(u.query).get('id', [''])[0] in ('ps5', 'playstation')

def article_content(html, url):
    if urllib.parse.urlparse(url).hostname == 'gall.dcinside.com' and 'write_div' in html:
        body = PostBody()
        body.feed(html)
        return ''.join(body.parts)
    return html

def plain(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()

def safe_public_url(url):
    try:
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("https","http") or not u.hostname or u.username or u.password:
            return False
        h = u.hostname.lower()
        if h in ("localhost", "local", "0.0.0.0") or h.endswith((".local", ".internal", ".test")):
            return False
        try:
            address = ipaddress.ip_address(h)
            if not address.is_global:
                return False
        except ValueError:
            if "." not in h:
                return False
        return True
    except (ValueError, TypeError):
        return False

def choose_link(article_url, links):
    """Prefer actual vendor raffle/product links over search/news wrappers."""
    options = []
    for href, label in links:
        url = urllib.parse.urljoin(article_url, unescape(href).strip())
        if not safe_public_url(url):
            continue
        u = urllib.parse.urlparse(url)
        if PATH_BAD.search(u.path):
            continue
        if not (PATH_GOOD.search(url) or ACTION_WORD.search(label)):
            continue
        if re.search(r"(?:중고|울버린|리퍼|해외직구|듀얼센스\s*세트)",label,re.I):
            continue
        original = urllib.parse.urlparse(article_url)
        if url.split("#")[0] == article_url.split("#")[0]:
            continue
        score = 0
        if PATH_GOOD.search(url):
            score += 4
        if ACTION_WORD.search(label):
            score += 2
        if PRODUCT.search(label + " " + urllib.parse.unquote(u.path)):
            score += 4
        host = u.hostname.lower()
        if any(host == d or host.endswith("."+d) for d in (
            "playshop.co.kr", "ojinplaystation.cafe24.com", "get-these.com",
            "gamewoori.com", "ssg.com", "compuzone.co.kr",
            "gmarket.co.kr", "naver.com", "coupang.com", "11st.co.kr",
            "lotteon.com", "e-himart.co.kr"
        )):
            score += 3
        if host in ("news.google.com", "google.com"):
            score -= 6
        # Generic 'buy' navigation to homepage should not be accepted as product link.
        if not PATH_GOOD.search(url) and not PRODUCT.search(label):
            score -= 3
        if score >= 5:
            options.append((score, url))
    return sorted(options, key=lambda x:(-x[0],x[1]))[0][1] if options else None

def deadline_from_text(text):
    match = DATE_END.search(text)
    if not match:
        return None
    try:
        year, mo, day, hh, minute = match.groups()[:5]
        return datetime(int(year),int(mo),int(day),int(hh or 23),int(minute or 59),tzinfo=KST)
    except (ValueError, TypeError):
        return None

def review(title, article_url, html="", description="", now=None):
    """Review title and available body for a current actionable PS5 Pro sale.

    Return None for clearly ended or unrelated listings. If body
    is inaccessible, preserve article as an unverified lead, not verified stock.
    """
    now = now or datetime.now(KST)
    title = re.sub(r"\s+", " ", unescape(title)).strip()
    source = Article()
    scoped_html = article_content(html or '', article_url)
    source.feed(scoped_html)
    article_text = re.sub(r"\s+", " ", unescape(" ".join(source.text))).strip()
    description_text = plain(description or "")
    context = " ".join([title, description_text, article_text[:20000]])
    # Read the body BEFORE deciding. In a PS gallery, '프로', store-only,
    # '취소분 샀다', or a bare product link can be an actionable lead.
    links = list(source.links)
    other = Article()
    other.feed(description or '')
    links.extend(other.links)
    links.extend((u.rstrip('.,);]'), '링크') for u in re.findall(r'https?://[^\s<>"\']+', unescape(article_text+' '+description_text)))
    destination = choose_link(article_url, links)
    scoped = is_ps_board(article_url)
    product = bool(PRODUCT.search(context) or (scoped and re.search(r'프로|\bpro\b',context,re.I)))
    platform = bool(PLATFORM.search(context) or scoped)
    images = [urllib.parse.urljoin(article_url, u) for u in source.images if safe_public_url(urllib.parse.urljoin(article_url,u))]
    signal = bool(SALE.search(context) or COMMUNITY_CUES.search(context) or destination
                  or (product and images))
    implied = scoped and bool(RETAILER.search(context) or COMMUNITY_CUES.search(context) or destination)
    if not ((product or platform or implied) and signal):
        return None
    # Keep uncertain leads, including bundles/price mismatches, as the user
    # requested. A lead is never represented as validated stock or a purchase.
    if (CLOSED_TITLE.search(title) or NEGATIVE.search(title)) and not REOPENED.search(title):
        return None
    if re.search(r'보호필름|기프트\s*카드|충전기|게임\s*타이틀',title,re.I):
        return None
    warnings = []
    if not product:
        warnings.append('PS5 Pro 여부 미확인: 게시판·본문 맥락상 구매 관련 제보')
    if BAD_GOODS.search(title) or re.search(r'번들|인질|듀센|\+\s*듀얼센스',title,re.I):
        warnings.append('구성 확인 필요: 번들·중고·기타 조건이 포함될 수 있음')
    if CLOSED_TITLE.search(context) or NEGATIVE.search(context):
        warnings.append('품절·종료 언급 포함: 현재 상태 재확인 필요')
    expiry = deadline_from_text(context)
    if expiry and expiry < now:
        return None
    # A known price over budget should not be presented as eligible when
    # there is no qualifying price in the post itself.
    # Prices in the body may be unrelated to the headline, so keep them
    # information-only rather than asserting the final checkout price.
    title_prices = [int(v.replace(",","")) for v in PRICE.findall(title)]
    if title_prices and min(title_prices) > PRICE_CEILING:
        warnings.append('기존 희망가격 초과: 정보 알림이며 구매 권유 아님')
    action = destination or article_url
    if not safe_public_url(action):
        return None
    return {
        "title": title,
        "link": action,
        "source_url": article_url,
        "direct_link": bool(destination),
        "deadline": expiry.strftime("%Y-%m-%d %H:%M KST") if expiry else None,
        "price_in_title": min(title_prices) if title_prices else None,
        "reviewed_body": bool(article_text),
        "warnings": warnings,
        "product_confirmed": product,
        "evidence": context[:500],
        "images": images[:3],
    }

def inspect(title, url, description="", fetcher=None, now=None):
    if not safe_public_url(url):
        return None
    html = ""
    try:
        if fetcher is not None:
            html = fetcher(url)
        elif monitor_window.is_active_at():
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; PS5ProSaleNotice/1.0)",
                "Accept": "text/html",
            })
            with urllib.request.urlopen(req, timeout=6) as response:
                data = response.read(500_000)
                html = data.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception as exc:
        print(f"Sale article unavailable: {type(exc).__name__}")
    return review(title, url, html, description, now)

def format_alert(lead, source, published):
    kind = "응모·판매 정보" if ("응모" in lead["title"] or "추첨" in lead["title"]) else "판매·특가 정보"
    direct = "게시글 내 직접 링크" if lead["direct_link"] else "게시글 링크 (직접 링크 미확인)"
    lines = [
        f"[PS5 Pro {kind} — 확인 필요]",
        f"출처: {source}",
        f"제목: {lead['title']}",
        f"{'게시 시각' if published else '발견 시각 (게시 시각 미확인)'}: {(published or datetime.now(KST)).astimezone(KST):%m-%d %H:%M} KST",
        f"이동: {direct}",
        lead["link"],
    ]
    if lead["price_in_title"]:
        lines.append(f"게시글 제목 가격: {lead['price_in_title']:,}원 (결제가는 재확인)")
    if lead["deadline"]:
        lines.append(f"게시글 마감 시각: {lead['deadline']}")
    lines.extend(lead.get('warnings', []))
    if lead.get('images'):
        lines.extend(['본문 사진 (가격·구매 화면은 원문에서 확인):', lead['images'][0]])
    if lead['direct_link']:
        lines.extend(['원문:', lead['source_url']])
    if not lead["direct_link"]:
        lines.append("판매처 직접 링크 추출 실패. 게시글의 구매·응모 링크를 확인하세요.")
    lines.append("실제 재고·접수 가능 여부는 판매처 페이지에서 확인하세요.")
    return "\n".join(lines)
