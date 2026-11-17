"""Real missed community language plus delivery/window regressions."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import sale_link_review as s
import notifications as n
import dcinside_watch as d
import promo_watch as p
import web_discovery as w

NOW=datetime(2026,11,17,13,0,tzinfo=s.KST)
POST='https://gall.dcinside.com/mgallery/board/view/?id=ps5&no=1'

class IncidentTests(unittest.TestCase):
    def test_real_posts_reach_lead_stage(self):
        rows=json.loads(Path(__file__).with_name('observed_community_posts.json').read_text(encoding='utf-8'))
        positive={'728239','728242','728245','728246','728250','728255','728256','728265','728331','728334','728336','728339','728347','728073'}
        for row in rows:
            if row['id'] in positive:
                with self.subTest(row['id']):
                    self.assertIsNotNone(s.review(row['title'],row['url'],
                        '<div class="write_div">'+row['body']+'</div>',now=NOW))

    def test_title_omits_every_product_word_but_body_supplies_it(self):
        lead=s.review('링크',POST,'<div class="write_div">프로 풀렸다 <a href="https://www.coupang.com/vp/products/123">링크</a></div>',now=NOW)
        self.assertEqual(lead['link'],'https://www.coupang.com/vp/products/123')

    def test_link_only_body_in_ps_gallery(self):
        lead=s.review('이거',POST,'<div class="write_div">https://www.coupang.com/vp/products/123</div>',now=NOW)
        self.assertTrue(lead['direct_link'])
        self.assertTrue(lead['warnings'])

    def test_image_only_post_is_not_silently_discarded(self):
        lead=s.review('프로 풀렸다',POST,'<div class="write_div"><img src="https://dcimg8.dcinside.co.kr/viewimage.php?id=1"></div>',now=NOW)
        self.assertTrue(lead['images'])
        self.assertIn('사진',s.format_alert(lead,'디시',NOW))

    def test_store_name_only_and_body_purchase_evidence(self):
        self.assertIsNotNone(s.review('쿠팡',POST,'<div class="write_div">듀센 2개에 1399000원 프로 지금 결제됨</div>',now=NOW))

    def test_site_ads_and_related_threads_are_not_body_evidence(self):
        html='<div class="write_div">프레임 비교입니다</div><a href="https://www.coupang.com/vp/products/123">PS5 Pro 구매 링크</a>'
        self.assertIsNone(s.review('프로 그래픽 비교',POST,html,now=NOW))

    def test_reopened_after_soldout(self):
        self.assertIsNotNone(s.review('PS5 Pro 품절이었는데 다시 풀렸다',POST,now=NOW))
        self.assertIsNone(s.review('프로 안 풀림',POST,now=NOW))

    def test_body_link_shortener_is_kept(self):
        lead=s.review('프로 링크',POST,'<div class="write_div">https://link.coupang.com/a/Example</div>',now=NOW)
        self.assertEqual(lead['link'],'https://link.coupang.com/a/Example')

    def test_google_feed_does_not_gate_on_title_product_or_sale(self):
        raw='<rss><channel><item><title>링크</title><link>https://example.com/post</link><pubDate>Tue, 17 Nov 2026 04:00:00 GMT</pubDate><description>프로 물량</description></item></channel></rss>'
        with patch.object(p,'request',return_value=raw.encode()):
            self.assertEqual(len(list(p.read_feed('넓은검색','플스'))),1)

    def test_no_dedup_on_delivery_failure(self):
        html='<tr data-no="1"><td class="gall_date" title="2026-11-17 13:00:00"></td><a href="/mgallery/board/view/?id=ps5&no=1">프로 풀렸다</a></tr>'
        with patch.object(d,'GALLERIES',[('ps5','ps5','https://gall.dcinside.com/mgallery/board/lists/?id=ps5')]), patch.object(d,'load_state',return_value=({'ps5':[]},'sha')), patch.object(d,'request',return_value=html.encode()), patch.object(d.sale_link_review,'inspect',return_value=s.review('프로 풀렸다',POST,now=NOW)), patch.object(d,'telegram',side_effect=RuntimeError('delivery failed')), patch.object(d,'save_state') as save, patch.object(d,'datetime') as clock:
            clock.now.return_value=NOW;clock.fromisoformat=datetime.fromisoformat
            with self.assertRaises(RuntimeError):d.main()
            self.assertFalse(save.called)

    def test_delivery_checks_api_receipt(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"ok":true,"result":{"message_id":7,"date":1}}'
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test','MONITOR_DRY_RUN':'0'}), patch.object(n.monitor_window,'is_active_at',return_value=True),patch.object(n.urllib.request,'urlopen',return_value=response):
            self.assertEqual(n.telegram('test')['message_id'],7)

    def test_cutoff_blocks_real_transport(self):
        with patch.object(n.monitor_window,'is_active_at',return_value=False),patch.object(n.urllib.request,'urlopen') as transport:
            with self.assertRaises(RuntimeError):n.telegram('test')
            transport.assert_not_called()

    def test_transport_failure_does_not_expose_token(self):
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'SECRET','TELEGRAM_CHAT_ID':'test','MONITOR_DRY_RUN':'0'}),patch.object(n.monitor_window,'is_active_at',return_value=True),patch.object(n.urllib.request,'urlopen',side_effect=ValueError('https://api.telegram.org/botSECRET')):
            with self.assertRaises(RuntimeError) as caught:n.telegram('test')
            self.assertNotIn('SECRET',str(caught.exception))

if __name__=='__main__':unittest.main()
