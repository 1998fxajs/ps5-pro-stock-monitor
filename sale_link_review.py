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
import post_content
import image_ocr

KST = ZoneInfo("Asia/Seoul")
PRODUCT = re.compile(r"(?:\bps\s*5\s*pro\b|play\s*station\s*5\s*(?:pro|프로)|ps\s*5\s*프로|플레이\s*스테이션\s*5?\s*(?:프로|pro)|플스\s*5?\s*(?:프로|pro)|CFI[-\s]*7122B)", re.I)
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
    return post_content.extract(html, url)[0]

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
        if re.search(r"(?:중고|리퍼|해외직구)",label,re.I):
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

PRO_SHORT = re.compile(r'(?<![가-힣a-z])(?:프로|pro)(?=$|[\s\d!?+~,.;:]|[가는를도에로만랑와은])', re.I)
NON_CONSOLE = re.compile(r'듀얼센스|듀센|컨트롤러|패드|포탈|포털|portal|헤드셋|이어버드|충전|거치대|스탠드|보호필름|케이스|커버|디스크\s*드라이브|PS\s*(?:N|PLUS|플러스)|프슨플|구독|기프트|DLC|게임\s*(?:타이틀|패키지|소프트)|지원\s*게임', re.I)
HARDWARE = re.compile(r'본체|콘솔|2\s*TB|CFI[-\s]*7122B',re.I)
RESTOCK = re.compile(r'풀렸|풀림|풀린|떴|떳|뜬|입고|취소분|취소\s*할|물량|응모|추첨',re.I)
OWNER = re.compile(r'^(?:\s*(?:오우너|소유|보유|쓰고|사용|가지고|지원)|(?:에서|으로|로)\s*(?:플레이|돌리|게임))',re.I)
COMPATIBILITY = re.compile(r'(?:PS\s*5\s*Pro|플스\s*5?\s*프로|프로)\s*(?:용|호환|전용|에서|지원)',re.I)

class ReviewUnavailable(RuntimeError):
    """Body could not be read; keep it pending instead of marking it reviewed."""

def has_pro(text, scoped):
    match=PRODUCT.search(text) or (PRO_SHORT.search(text) if scoped else None)
    return bool(match and not OWNER.search(text[match.end():]))

def purchase_signal(text):
    return bool(SALE.search(text) or COMMUNITY_CUES.search(text))

def console_subject(text, scoped):
    if not has_pro(text,scoped):return False
    if COMPATIBILITY.search(text):return False
    # Accessory references can be a console bundle; ownership/compatibility
    # mentions do not turn an accessory or game into a console offer.
    if NON_CONSOLE.search(text):
        bundle=bool(re.search(r'본체|콘솔|2\s*TB',text,re.I) or re.search(r'(?:프로|pro)\s*\+|(?:프로|pro).*?(?:번들|세트|인질|포함)|(?:번들|세트|인질).*?(?:프로|pro)',text,re.I)
                    or (PRICE.search(text) and re.search(r'(?:프로|pro)\s*(?:지금\s*)?(?:결제|구매|풀렸)',text,re.I)))
        if re.search(r'(?:드라이브|듀얼센스|듀센|컨트롤러|패드).*?단품',text,re.I):return False
        if not bundle:return False
    return True

def review(title, article_url, html="", description="", now=None, image_text="", linked_text="", image_status=None):
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
    # Feed descriptions are candidate hints, never proof when the source
    # body contradicts them. Keep post, image and linked subject separately.
    context = " ".join([title, article_text[:20000], image_text, linked_text])
    # Read the body BEFORE deciding. In a PS gallery, '프로', store-only,
    # '취소분 샀다', or a bare product link can be an actionable lead.
    links = list(source.links)
    other = Article()
    other.feed(description or '')
    links.extend(other.links)
    links.extend((u.rstrip('.,);]'), '링크') for u in re.findall(r'https?://[^\s<>"\']+', unescape(article_text+' '+description_text)))
    destination = choose_link(article_url, links)
    scoped = is_ps_board(article_url)
    images = [urllib.parse.urljoin(article_url, u) for u in source.images if safe_public_url(urllib.parse.urljoin(article_url,u))]
    title_product=console_subject(title,scoped)
    body_product=any(console_subject(part,scoped) and purchase_signal(part)
                     for part in re.split(r'[\n.!?。]+',article_text))
    linked_product=console_subject(linked_text,False)
    image_product=console_subject(image_text,False)
    product=title_product or body_product or linked_product or image_product
    signal=purchase_signal(title+' '+article_text) or bool(destination) or bool(image_product and re.search(r'구매하기|바로구매|장바구니|재입고',image_text))
    # A board name, generic shopping link, or image presence is not console
    # evidence. An unnamed *restock* in the PS board is an uncertain lead;
    # generic "bought it" requires the linked product or image to identify it.
    implied=scoped and not NON_CONSOLE.search(context) and bool(
        re.search(r'(?:쿠팡|네이버|플레이샵|겟디즈|겜우리|컴퓨존|SSG|쓱)(?:에|에서)?\s*(?:(?:방금|지금|또|다시)\s*)?(?:풀렸|풀림|풀린|떴)',title,re.I)
        or re.search(r'^(?:신규\s*물량|물량\s*입고|취소분\s*샀)',title)
        or (RETAILER.search(title) and purchase_signal(title) and re.search(r'플스인거|본체|콘솔',article_text)))
    if not ((product or implied) and signal):
        return None
    # When the title explicitly sells another class of goods, only actual
    # console bundle evidence from that post can override it.
    if NON_CONSOLE.search(title) and not title_product and not linked_product and not image_product and not body_product:
        return None
    # Keep uncertain leads, including bundles/price mismatches, as the user
    # requested. A lead is never represented as validated stock or a purchase.
    if (CLOSED_TITLE.search(title) or NEGATIVE.search(title)) and not REOPENED.search(title):
        return None
    warnings = []
    if not product:
        warnings.append('PS5 Pro 여부 미확인: 본문을 읽은 재입고 제보이며 기종 확인 필요')
    if images:
        warnings.append('본문 사진 OCR: '+(image_status or ('판독됨 · 오인식 가능' if image_text else '미판독 · 사진 자체를 본체 증거로 사용하지 않음')))
    if re.search(r'풀거\s*같|풀릴\s*듯|새야겠',context):warnings.append('작성자의 예상 포함: 실제 판매 시작 미확인')
    if BAD_GOODS.search(title) or re.search(r'번들|세트|인질|듀센|\+\s*(?:듀얼센스|디스크)',title,re.I):
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
        "reviewed_body": bool(article_text or images),
        "warnings": warnings,
        "product_confirmed": product,
        "evidence": context[:500],
        "images": images[:3],
        "image_text": image_text[:500],
        "linked_subject": linked_text[:300],
        "decision_basis": 'console subject' if product else 'unnamed restock report',
    }

def fetch_public(url, referer=None, binary=False):
    if not monitor_window.is_active_at():raise ReviewUnavailable('Monitoring window ended')
    if not safe_public_url(url):raise ReviewUnavailable('Invalid public URL')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not safe_public_url(newurl):raise ReviewUnavailable('Invalid redirect')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    headers={'User-Agent':'Mozilla/5.0 (compatible; PS5ProSaleNotice/1.0)','Accept':'image/*' if binary else 'text/html'}
    if referer:headers['Referer']=referer
    req=urllib.request.Request(urllib.parse.quote(url,safe=':/?&=%#+'),headers=headers)
    with urllib.request.build_opener(Redirect()).open(req,timeout=6) as response:
        raw=response.read(4_000_001 if binary else 1_000_000)
        return raw if binary else raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')

def inspect(title, url, description="", fetcher=None, now=None, ocr=None):
    if not safe_public_url(url):
        return None
    try:
        html=(fetcher or fetch_public)(url)
    except Exception as exc:
        raise ReviewUnavailable('Post fetch failed: '+type(exc).__name__) from None
    main,metadata=post_content.extract(html,url)
    if not main or re.search(r'<title[^>]*>\s*(?:just a moment|access denied|attention required)',html,re.I):
        raise ReviewUnavailable('Recognizable post body unavailable')
    page=Article();page.feed(main)
    text=' '.join(page.text)
    if not text.strip() and not page.images and not page.links:raise ReviewUnavailable('Empty post')
    linked='';image_text='';statuses=[]
    links=page.links+[(u,'링크') for u in re.findall(r'https?://[^\s<>"\']+',text)]
    destination=choose_link(url,links)
    if destination:
        try:
            linked_html=(fetcher or fetch_public)(destination)
            linked_main,linked_meta=post_content.extract(linked_html,destination)
            # Read the product heading, not every other item on the shop page.
            linked=linked_meta.get('heading') or linked_meta.get('og:title','')
        except Exception:statuses.append('연결 상품 페이지 접근 불가')
    # OCR candidate pictures only, not every screenshot in unrelated game chat.
    candidate=purchase_signal(title+' '+text) or bool(destination) or has_pro(title,is_ps_board(url))
    if candidate:
        for href in page.images[:2]:
            image_url=urllib.parse.urljoin(url,href)
            if not safe_public_url(image_url):continue
            try:
                if ocr:recognized,status=ocr(image_url,url)
                else:recognized,status=image_ocr.recognize(fetch_public(image_url,referer=url,binary=True))
                image_text+='\n'+recognized;statuses.append(status)
            except Exception:statuses.append('image unavailable')
    result=review(title,url,html,description,now,image_text,linked,'; '.join(statuses))
    if result is None and candidate and page.images and not image_text.strip():
        raise ReviewUnavailable('Candidate image could not be read; retained for retry')
    print('REVIEW '+json.dumps({'title':title,'url':url,'body_read':True,'decision':'lead' if result else 'reject',
          'basis':result.get('decision_basis') if result else 'no console purchase evidence',
          'linked_subject':linked[:180],'ocr':statuses,'ocr_text_excerpt':image_text[:450] if candidate else ''},ensure_ascii=False),flush=True)
    if result:
        result['published_hint']=metadata.get('article:published_time') or metadata.get('datepublished') or metadata.get('date')
    return result

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
