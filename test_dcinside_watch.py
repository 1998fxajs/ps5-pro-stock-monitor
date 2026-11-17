"""Offline regression tests for public DC Inside post discovery."""
import unittest

import dcinside_watch as d

class DCInsideTests(unittest.TestCase):
    def test_public_hotdeal_post(self):
        source = d.GALLERIES[0][2]
        html = ('<a href="/mgallery/board/view/?id=hotdeal1&no=338">'
                '[지마켓] PS5 Pro 재입고 129만8천원</a>')
        posts = d.parse_posts(html, "hotdeal1", source)
        self.assertEqual(len(posts), 1)
        self.assertIn("338", posts)
        self.assertTrue(d.relevant(posts["338"][0]))
        self.assertIn("id=hotdeal1&no=338", posts["338"][1])

    def test_dc_playstation_post(self):
        source = d.GALLERIES[2][2]
        html = ('<a href="/board/view/?id=playstation&no=326815">'
                'PS5 프로 겟디즈 판매 오픈</a>')
        posts = d.parse_posts(html, "playstation", source)
        self.assertEqual(len(posts), 1)
        self.assertTrue(d.relevant(posts["326815"][0]))

    def test_wrong_forum_or_host_rejected(self):
        source = d.GALLERIES[0][2]
        html = ('<a href="https://fakegall.dcinside.com/mgallery/board/view/?id=hotdeal1&no=1">PS5 Pro 판매</a>'
                '<a href="/mgallery/board/view/?id=other&no=2">PS5 Pro 판매</a>')
        self.assertEqual(d.parse_posts(html, "hotdeal1", source), {})

    def test_ps_gallery_posts_reach_body_review(self):
        for title in ('쿠팡','링크','프로 풀렸다','이거','PS5 Pro 그래픽 성능 분석'):
            self.assertTrue(d.relevant(title,'ps5'))

    def test_comment_count_cannot_overwrite_title(self):
        url='https://gall.dcinside.com/mgallery/board/lists/?id=ps5'
        html='<a href="/mgallery/board/view/?id=ps5&no=728242">프로 풀렸다</a><a href="/mgallery/board/view/?id=ps5&no=728242&t=cv"><span>[5]</span></a>'
        self.assertEqual(d.parse_posts(html,'ps5',url)['728242'][0],'프로 풀렸다')

    def test_regular_board_url_is_not_doubled(self):
        html='<a href="/board/view/?id=playstation&no=12">프로 링크</a>'
        self.assertEqual(d.parse_posts(html,'playstation',d.GALLERIES[2][2])['12'][1],
                         'https://gall.dcinside.com/board/view/?id=playstation&no=12')

    def test_coverage(self):
        self.assertEqual({x[1] for x in d.GALLERIES},
                         {"hotdeal1", "discountproduct", "playstation", "ps5"})

if __name__ == "__main__":
    unittest.main()
