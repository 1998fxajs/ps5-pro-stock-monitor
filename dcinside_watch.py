#!/usr/bin/env python3
"""Best-effort public DC Inside forum announcement monitor.

Only reads publicly accessible first-page post titles; no login, CAPTCHA,
private endpoints, proxy, rate-limit bypass or purchase automation.
Messages are leads, never verified in-stock claims.
"""
import base64
import json
import re
import urllib.parse
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError

import monitor_window
import sale_link_review
from promo_watch import INCLUDE, EXCLUDE, SIGNAL, github, request, telegram

STATE_PATH = "dcinside_seen.json"
GALLERIES = [
    ("핫딜", "hotdeal1", "https://gall.dcinside.com/mgallery/board/lists/?id=hotdeal1"),
    ("할인상품", "discountproduct", "https://gall.dcinside.com/mgallery/board/lists/?id=discountproduct"),
    ("PlayStation", "playstation", "https://gall.dcinside.com/board/lists/?id=playstation"),
]
MAX_POSTS = 150

class PostLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": []}
    def handle_data(self, data):
        if self.current:
            self.current["text"].append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current["href"], "".join(self.current["text"]).strip()))
            self.current = None

def relevant(title):
    cleaned = re.sub(r"\s+", " ", unescape(title)).strip()
    return (bool(INCLUDE.search(cleaned))
            and bool(SIGNAL.search(cleaned))
            and not bool(EXCLUDE.search(cleaned)))

def parse_posts(content, board_id, source_url):
    parser = PostLinks()
    parser.feed(content)
    out = {}
    for href, title in parser.links:
        url = urllib.parse.urljoin(source_url, unescape(href))
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname not in ("gall.dcinside.com", "www.gall.dcinside.com"):
            continue
        if "/board/view" not in parsed.path:
            continue
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("id", [""])[0] != board_id:
            continue
        number = query.get("no", [""])[0]
        if not re.fullmatch(r"\d+", number):
            continue
        # Canonical link avoids duplicate alerts for tracking query params.
        base = "mgallery" if board_id != "playstation" else "board"
        post_url = f"https://gall.dcinside.com/{base}/board/view/?id={board_id}&no={number}"
        title = re.sub(r"\s+", " ", unescape(title)).strip()
        if title:
            out[number] = (title, post_url)
    return out

def load_state():
    try:
        obj = github(f"contents/{STATE_PATH}")
        return json.loads(base64.b64decode(obj["content"]).decode("utf-8")), obj["sha"]
    except HTTPError as exc:
        if exc.code == 404:
            return {}, None
        raise

def save_state(data, sha):
    payload = {
        "message": "chore: record DC Inside forum posts",
        "content": base64.b64encode((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    github(f"contents/{STATE_PATH}", payload)

def main():
    if not monitor_window.is_active_at():
        print("DC Inside monitoring expired")
        return
    state, sha = load_state()
    changed = False
    success = 0
    new_count = 0
    for label, board_id, url in GALLERIES:
        try:
            raw = request(url)
            # DC Inside pages are normally UTF-8, with EUC-KR fallback.
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError:
                html = raw.decode("euc-kr", errors="replace")
            posts = parse_posts(html, board_id, url)
            if not posts:
                print(f"DC {label}: no recognizable post links; not recording empty baseline")
                continue
            success += 1
            old = state.get(board_id)
            if old is None:
                state[board_id] = list(posts)[-MAX_POSTS:]
                changed = True
                print(f"DC {label}: initial baseline {len(posts)} posts; no retrospective alerts")
                continue
            seen = set(old)
            fresh = [(num, *posts[num]) for num in posts if num not in seen]
            for number, title, post_url in fresh:
                if relevant(title):
                    # Open the public post when possible and prefer its actual
                    # purchase or raffle URL over just the discussion link.
                    lead = sale_link_review.inspect(title, post_url)
                    if lead is None:
                        print(f"DC {label}: skipped ended/irrelevant sale report {number}")
                        continue
                    direct_kind = "게시글 내 구매·응모 링크" if lead["direct_link"] else "게시글 (직접 링크 미확인)"
                    telegram("[PS5 Pro 디시 새 판매 정보 - 확인 필요]\n"
                             f"갤러리: {label}\n제목: {title}\n"
                             f"{direct_kind}: {lead['link']}\n"
                             f"게시글 원문: {post_url}\n"
                             "상품 구성·가격·실제 재고를 확인하세요.")
                    new_count += 1
            updated = (list(dict.fromkeys(old + list(posts)))[-MAX_POSTS:])
            if updated != old:
                state[board_id] = updated
                changed = True
            print(f"DC {label}: {len(posts)} posts, {len(fresh)} new; {new_count} matching alerts overall")
        except Exception as exc:
            print(f"DC {label}: unavailable ({type(exc).__name__}: {exc})")
    if not success:
        raise RuntimeError("All DC Inside public forum lists unavailable or unparseable")
    if changed:
        save_state(state, sha)
    print(f"DC Inside discovery finished; galleries={success}/{len(GALLERIES)}, alerts={new_count}")

if __name__ == "__main__":
    main()
