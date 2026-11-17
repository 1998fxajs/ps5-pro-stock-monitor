"""False alerts, main-post isolation, freshness and actual-reading contracts."""
import unittest
from unittest.mock import patch
from datetime import datetime
import sale_link_review as s
import web_discovery as w
import promo_watch as p
import dcinside_watch as d
import catalog_watch as c

NOW=datetime(2026,11,17,14,0,tzinfo=s.KST)
POST='https://gall.dcinside.com/mgallery/board/view/?id=ps5&no=999'

class ContextTests(unittest.TestCase):
    def test_game_accessory_subscription_subjects_are_not_console_offers(self):
        rows=[
            ('PS5 어쌔신 크리드 섀도우스 할인','쿠팡에서 39800원 판매 중'),
            ('듀얼센스 블랙 하나 지름','블랙 사고싶었는데 쿠팡에서 하나 지름 이걸로 그타6 해야지'),
            ('psn 구독 고수들은 이렇게 함??','지금 연장유저 아닌 이상 블프 기준 최대한 빠르게 결제'),
            ('레데리2, 위쳐3 뭐 살까 ?','둘다할인해서 본인 프로 오우너고 그타 예구한 상태임'),
            ('PS5 Pro 보호필름 특가','PS5 Pro 전용 보호필름 9800원 구매 링크'),
            ('PS5 Pro 지원 게임 할인','PS5 Pro로 플레이 가능한 게임을 구매하세요'),
            ('PS5 GTA6 예약구매','PlayStation5 게임 패키지 쿠팡 링크'),
            ('쿠팡 어크 풀렸다','39800원 지금 구매됨'),
            ('PS5 Pro 디스크 드라이브 단품','PS5 Pro 호환 상품 판매'),
            ('PS5 Pro 세트 판매','본체 미포함. 듀얼센스만 판매합니다'),
        ]
        for title,body in rows:
            with self.subTest(title=title):self.assertIsNone(s.review(title,POST,'<div class="write_div">'+body+'</div>',now=NOW))

    def test_main_post_isolated_from_related_game_and_console_ads(self):
        html='<html><nav>PS5 Pro 구매</nav><article><h1>어크 할인</h1><p>게임 특가 39800원</p><aside><a href="https://www.coupang.com/vp/products/123">PS5 Pro 구매</a></aside></article><footer>PS5 Pro 재고</footer></html>'
        self.assertIsNone(s.review('PS5 어크 할인','https://example.com/posts/1',html,now=NOW))
        self.assertNotIn('PS5 Pro',s.article_content(html,'https://example.com/posts/1'))

    def test_homepage_is_not_a_read_article(self):
        html='<html><body><nav>PS5 Pro 구매</nav><a href="https://www.coupang.com/vp/products/123">상품 구매</a></body></html>'
        with self.assertRaises(s.ReviewUnavailable):s.inspect('PlayStation 공식 사이트','https://www.playstation.com/ko-kr/',fetcher=lambda _:html)

    def test_unreachable_and_challenge_pages_are_pending(self):
        with self.assertRaises(s.ReviewUnavailable):s.inspect('프로 풀렸다',POST,fetcher=lambda _: (_ for _ in ()).throw(OSError('403')))
        with self.assertRaises(s.ReviewUnavailable):s.inspect('프로 풀렸다',POST,fetcher=lambda _:'<html><title>Just a moment...</title><main>Verifying</main></html>')

    def test_ambiguous_link_reads_destination_before_accepting(self):
        html='<div class="write_div"><a href="https://www.coupang.com/vp/products/123">링크</a></div>'
        visited=[]
        def fetch(url):
            visited.append(url)
            return html if url==POST else '<article><h1>PS5 어쌔신 크리드 섀도우스</h1>게임 구매</article>'
        self.assertIsNone(s.inspect('링크',POST,fetcher=fetch,now=NOW))
        self.assertEqual(len(visited),2)

    def test_purchase_photo_is_not_a_remaining_buying_opportunity(self):
        html='<div class="write_div"><img src="https://dcimg8.dcinside.co.kr/example.jpg"></div>'
        yes=s.inspect('나도 이제야 샀다',POST,fetcher=lambda _:html,ocr=lambda *_:('PlayStation5 Pro 콘솔 2TB 1,399,000원','OCR read'),now=NOW)
        no=s.inspect('나도 이제야 샀다',POST,fetcher=lambda _:html,ocr=lambda *_:('어쌔신 크리드 섀도우스 39800원','OCR read'),now=NOW)
        self.assertIsNone(yes);self.assertIsNone(no)

    def test_price_and_bundle_are_not_exclusion_gates(self):
        for title in ['PS5 Pro + 듀얼센스 1,399,000원','플스5 프로 번들 재입고','PS5 Pro 본체 + 디스크 드라이브 판매','PS5 Pro 콘솔 액세서리 포함 세트 판매']:
            self.assertIsNotNone(s.review(title,POST,'<div class="write_div">지금 구매됨</div>',now=NOW))

    def test_mixed_korean_english_product_in_real_image(self):
        self.assertTrue(s.console_subject('플레이스테이션 5 Pro 콘솔 + PS5 듀얼센스 무선 컨트롤러 2p 세트',False))
        self.assertTrue(s.console_subject('플레이스테이션 5 Pro 2S\n\n+PS5\n\n무선 컨트\n롤러 2p 세트, CFI-\n7122B01',False))

    def test_console_picture_alone_is_not_sale_signal(self):
        self.assertIsNone(s.review('프로 그래픽 좋네',POST,'<div class="write_div"><img src="https://dcimg8.dcinside.co.kr/a.jpg"></div>',now=NOW,image_text='PlayStation5 Pro 콘솔 2TB'))

    def test_stale_or_unknown_date_web_result_never_alerts(self):
        self.assertFalse(w.is_recent({'title':'PS5 Pro 입고','link':'https://example.com/post'},now=NOW))
        self.assertFalse(w.is_recent({'title':'PS5 Pro 59일전','link':'https://hotdeal.zip/ps5-pro-x'},now=NOW))
        self.assertTrue(w.is_recent({'title':'PS5 Pro 2분전','link':'https://hotdeal.zip/ps5-pro-x'},now=NOW))
        self.assertTrue(w.is_recent({'title':'프로','link':POST,'published':'Tue, 17 Nov 2026 04:50:00 GMT'},now=NOW))

    def test_dry_run_cannot_consume_notification_state(self):
        with patch.dict('os.environ',{'MONITOR_DRY_RUN':'1'}),patch.object(p,'github') as pg,patch.object(d,'github') as dg,patch.object(c,'gh') as cg:
            p.save_state({'seen':['a']},'sha');d.save_state({'ps5':['1']},'sha');c.save({},'sha')
            pg.assert_not_called();dg.assert_not_called();cg.assert_not_called()

if __name__=='__main__':unittest.main()
