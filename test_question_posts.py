"""Question false alert recovered from the actual public post on Nov 17."""
import unittest
import sale_link_review as review

POST = 'https://gall.dcinside.com/mgallery/board/view/?id=ps5&no=728705'
TITLE = '플스 프로긴한데 gta6 다른사람들 하는거 보고 살까?'
BODY = ('너무 분량큰 오픈월드 내가 잘 안퍼먹기도하고 지금 사고 30퍼도 안한겜이 '
        '70만원어치 넘을거같음 아니면 그래도 오픈빨은 즐겨볼까 어떰 솔직히 돈은 충분함 - dc official App')


class QuestionPosts(unittest.TestCase):
    def test_actual_game_buying_question_has_no_console_offer(self):
        html = '<div class="write_div">'+BODY+'</div>'
        self.assertIsNone(review.inspect(TITLE, POST, fetcher=lambda _: html))

    def test_open_world_or_launch_hype_is_not_a_sale(self):
        for body in ('오픈월드 게임 기대된다', '오픈빨 즐겨야지'):
            self.assertIsNone(review.review('플스 프로 쓰는중', POST,
                                           '<div class="write_div">'+body+'</div>'))

    def test_availability_questions_are_not_affirmative_even_with_links(self):
        for title, body in [('프로 지금 구매 가능?', '살까 말까 고민임'),
                            ('프로 재고 있냐', '쿠팡 링크'),
                            ('플스 프로 살까?', '판매 페이지')]:
            html = '<div class="write_div">'+body+'<a href="https://www.coupang.com/vp/products/9804453589">구매 링크</a></div>'
            self.assertIsNone(review.review(title, POST, html,
                linked_text='PlayStation5 Pro 콘솔 2TB'))

    def test_actual_restock_reports_are_preserved(self):
        for title, body in [
            ('야 쿠팡에 플스5 프로 정가 풀림 빨리 살놈들 사라',
             '근데 듀센 추가로 하나 더 딸린 구성이라 140만임'),
            ('프로 풀렸다', ''),
            ('쿠팡에 프로 풀렸다는데?', '듀센 2개 포함'),
            ('신규 물량 입고 됐나보네', '오래버티는거 보니까'),
        ]:
            self.assertIsNotNone(review.review(title, POST,
                '<div class="write_div">'+body+'</div>'))

    def test_independent_explicit_stock_statement_still_alerts(self):
        self.assertIsNotNone(review.review('프로 살까?', POST,
            '<div class="write_div">쿠팡 지금 구매 가능. 재고 남아 있음.</div>'))


if __name__ == '__main__':
    unittest.main()
