"""Purchase/arrival stories must not masquerade as current buying opportunities."""
import unittest
from unittest.mock import Mock
import sale_link_review as s

POST = 'https://gall.dcinside.com/mgallery/board/view/?id=ps5&no=999'
PRODUCT = 'https://www.coupang.com/vp/products/9804453589'
PHOTO = '<img src="https://example.com/receipt.jpg">'


class PurchaseStories(unittest.TestCase):
    def test_personal_purchase_is_rejected_even_with_console_receipt_and_link(self):
        for title, body in [
            # Actual erroneous alert message_id=30, 2026-11-17 14:56 KST.
            # Title recovered from runner log; body is now unavailable.
            ('난 노말유저인데 올해 설날 세일때 크림에서 프로 샀다가', ''),
            ('프로 샀다', '드디어 구매 완료'),
            ('쿠팡 프로 구매함', '이걸 살려주네'),
            ('취소분 샀다', '적립 못해서 아쉽다'),
            ('방금 뜬 프로', '물량이 한개였나 나는 먹었다'),
            ('프로 배송 후기', '벌써 도착 ㅎㅎ'),
            ('집가서 설치한다', '노멀 초기화하고 프로 뜯고 사전다운로드 가즈아'),
        ]:
            with self.subTest(title=title):
                html='<div class="write_div">'+body+PHOTO+f'<a href="{PRODUCT}">구매 링크</a></div>'
                self.assertIsNone(s.review(title,POST,html,
                    image_text='PlayStation5 Pro 콘솔 2TB 1399000원 구매하기 주문완료',
                    linked_text='PlayStation5 Pro 콘솔'))

    def test_purchase_story_with_explicit_remaining_stock_still_alerts(self):
        lead=s.review('프로 샀다',POST,'<div class="write_div">쿠팡 아직 재고 있음. 지금 구매 가능</div>')
        self.assertIsNotNone(lead)
        self.assertIn('current availability',lead['decision_basis'])

    def test_purchase_questions_and_past_availability_are_not_current_stock(self):
        for body in ['아직 재고 있나요?', '지금 구매 불가', '어제 재고 있다고 해서 샀다', '현재 재고 없음']:
            with self.subTest(body=body):
                self.assertIsNone(s.review('프로 구매 인증',POST,'<div class="write_div">'+body+'</div>'))

    def test_restock_and_future_cancellation_still_alert(self):
        self.assertIsNotNone(s.review('프로 풀렸다',POST))
        self.assertIsNotNone(s.review('쿠팡 프로 한대 취소할거야',POST,
            '<div class="write_div">새로 샀는데 16:30에 취소할거야. 주워가</div>'))

    def test_unread_receipt_does_not_retry_a_rejected_story(self):
        ocr=Mock(side_effect=RuntimeError('unavailable'))
        result=s.inspect('프로 샀다',POST,fetcher=lambda _: '<div class="write_div">'+PHOTO+'</div>',ocr=ocr)
        self.assertIsNone(result)
        ocr.assert_not_called()

    def test_direct_retail_product_discovery_remains_available(self):
        result=s.review('PlayStation5 Pro 콘솔',PRODUCT,'<article>상품 상세 구매하기</article>')
        self.assertIsNotNone(result)
        self.assertEqual(result['decision_basis'],'direct retailer product page; console identified')


if __name__=='__main__':
    unittest.main()
