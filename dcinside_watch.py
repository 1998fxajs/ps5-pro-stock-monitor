#!/usr/bin/env python3
"""Best-effort public DC Inside forum announcement monitor.

Reads public list pages and new post bodies; no login, CAPTCHA,
private endpoints, proxy, rate-limit bypass or purchase automation.
Messages are leads, never verified in-stock claims.
"""
import base64
import concurrent.futures
from datetime import datetime, timedelta
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
    ("플레이스테이션 5", "ps5", "https://gall.dcinside.com/mgallery/board/lists/?id=ps5"),
]
MAX_POSTS = 3000

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

def relevant(title, board_id=None):
    """Candidate admission only. PS galleries are read without a title gate."""
    return board_id in ('ps5', 'playstation') or bool(
        sale_link_review.PLATFORM.search(title) or INCLUDE.search(title)
        or sale_link_review.COMMUNITY_CUES.search(title))

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
        base = "/mgallery/board/view/" if board_id != "playstation" else "/board/view/"
        post_url = f"https://gall.dcinside.com{base}?id={board_id}&no={number}"
        title = re.sub(r"\s+", " ", unescape(title)).strip()
        # DC repeats the same URL for the comment-count anchor. It used to
        # overwrite real titles with '[3]', silently rejecting almost every post.
        if title and not re.fullmatch(r"\[?\s*\d+\s*\]?", title) and number not in out:
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
    if __import__('os').environ.get('MONITOR_DRY_RUN') == '1':return sha
    payload = {
        "message": "chore: record DC Inside forum posts",
        "content": base64.b64encode((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    response = github(f"contents/{STATE_PATH}", payload)
    return response['content']['sha']

def post_dates(html):
    dates = {}
    for row in re.findall(r'<tr\b[^>]*>.*?</tr>', html, re.I|re.S):
        number = re.search(r'data-no=["\'](\d+)', row)
        date = re.search(r'class=["\']gall_date["\'][^>]*title=["\']([^"\']+)', row)
        if number and date:
            try:
                dates[number.group(1)] = datetime.fromisoformat(date.group(1)).replace(tzinfo=sale_link_review.KST)
            except ValueError:
                pass
    return dates

def main():
    if not monitor_window.is_active_at():
        print("DC Inside monitoring expired")
        return
    state, sha = load_state()
    changed = False
    success = 0
    new_count = 0
    failures = []
    for label, board_id, url in GALLERIES:
        try:
            raw = request(url)
            # DC Inside pages are normally UTF-8, with EUC-KR fallback.
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError:
                html = raw.decode("euc-kr", errors="replace")
            posts = parse_posts(html, board_id, url)
            dates = post_dates(html)
            if not posts:
                print(f"DC {label}: no recognizable post links; not recording empty baseline")
                continue
            success += 1
            old = state.get(board_id, [])
            seen = set(old)
            # Catch bursts that move posts off page one; do not count pinned
            # notices as an overlap with the last inspected normal posts.
            for page in range(2, 4):
                normal = [n for n in posts if n in dates]
                if not old or any(n in seen for n in normal):
                    break
                extra = request(url+'&page='+str(page)).decode('utf-8',errors='replace')
                posts.update(parse_posts(extra, board_id, url))
                dates.update(post_dates(extra))
            now = datetime.now(sale_link_review.KST)
            processed = []
            fresh = []
            for number in sorted(posts, key=int, reverse=True):
                if number in seen:
                    continue
                # Bootstrap recent posts too; do not silently baseline a live sale.
                if number in dates and now-dates[number] > timedelta(hours=3):
                    processed.append(number)
                    continue
                title, post_url = posts[number]
                if relevant(title, board_id):
                    fresh.append((number,title,post_url))
                else:
                    processed.append(number)
            # Bounded concurrency keeps body inspection within the 5m cycle.
            # Excess candidates remain unseen and are retried next cycle.
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                tasks = {pool.submit(sale_link_review.inspect, title, post_url):(number,title,post_url)
                         for number,title,post_url in fresh[:60]}
                for task in concurrent.futures.as_completed(tasks):
                    number,title,post_url = tasks[task]
                    try:
                        lead = task.result()
                        if lead is not None:
                            telegram(sale_link_review.format_alert(lead, '디시 '+label, dates.get(number)))
                            new_count += 1
                        processed.append(number)
                    except Exception as exc:
                        failures.append(f'{board_id}/{number}: {type(exc).__name__}')
                        print(f'DC alert/review failed; retained for retry: {board_id}/{number} {type(exc).__name__}')
            updated = list(dict.fromkeys(old + processed))[-MAX_POSTS:]
            if updated != old:
                state[board_id] = updated
                changed = True
            print(f"DC {label}: {len(posts)} posts, {len(fresh)} new; {new_count} matching alerts overall")
        except Exception as exc:
            failures.append(f'{board_id}: {type(exc).__name__}')
            print(f"DC {label}: unavailable ({type(exc).__name__})")
    if not success:
        raise RuntimeError("All DC Inside public forum lists unavailable or unparseable")
    if changed:
        save_state(state, sha)
    print(f"DC Inside discovery finished; galleries={success}/{len(GALLERIES)}, alerts={new_count}")
    if failures:
        raise RuntimeError('Partial DC failure: '+'; '.join(failures))

if __name__ == "__main__":
    main()
