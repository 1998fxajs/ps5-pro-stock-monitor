# PS5 Pro Stock & Deal Monitor

국내 PS5 Pro 2TB **신품 본체 단품** 판매·입고·프로모션을 찾아 텔레그램으로 알리는 무료 GitHub Actions 프로젝트입니다. 게임 개발 저장소와 독립적으로 운영합니다.

## 가격 및 구매 정책

- 단품 정가 우선: **1,298,000원 이하**에서 재고 확인 알림.
- 최대 1,380,000원 상품 및 추첨·프로모션은 **정보 확인용 알림**으로만 취급.
- 추가 컨트롤러·디스크 드라이브 번들, 중고, 리퍼, 해외직구, 울버린 세트는 자동 구매 대상에서 제외.
- **구매·로그인·결제 자동화 없음.** 기존 매크로의 실제 소스는 확보하지 못했습니다. 자동 구매 1대 제한은 도입 시 별도 검증 필요.
- 가격이나 재고가 불확실한 사이트를 구매 가능하다고 확정하지 않습니다.

## 작동하는 워크플로

1. **[판매처 감시](https://github.com/1998fxajs/ps5-pro-stock-monitor/actions/workflows/retail-watch.yml)**: 겜우리, 이마트몰/SSG, 컴퓨존, 겟디즈의 공개 단품 상품 페이지를 약 5분 주기로 조회. GitHub Actions 실행시각은 지연되거나 누락될 수 있습니다.
2. **[판매글·특가·추첨 발견](https://github.com/1998fxajs/ps5-pro-stock-monitor/actions/workflows/promo-watch.yml)**: Google 뉴스 RSS에서 PS5 Pro, PS5프로, 플레이스테이션5 프로, 플스5프로, CFI-7122B 및 G마켓 전용 검색을 포함한 11개 검색 그룹을 확인. 뽐뿌 공개 RSS 두 곳도 별도로 시도합니다.
3. **[텔레그램 메시지 테스트](https://github.com/1998fxajs/ps5-pro-stock-monitor/actions/workflows/test-telegram.yml)**: 수동 테스트. 사용자 휴대폰 수신 확인 완료.

모든 알림은 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` GitHub Actions Secrets를 통해 전송합니다. 자격정보를 코드에 업로드하지 마세요.

## 직접 상품 링크

| 판매처 | URL | 마지막 검증 결과 |
|---|---|---|
| 겜우리 | https://www.gamewoori.com/product/detail.html?product_no=16602 | 상품 페이지 조회, 품절 표시 감지 |
| 이마트몰/SSG | https://emart.ssg.com/item/itemDtl.ssg?itemId=1000619325394 | 페이지 조회, 상품명 자동 확인 실패 -> 불명 |
| 컴퓨존 | https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1315525 | 페이지 조회, 재고 확정 불가 -> 불명 |
| 겟디즈 | https://get-these.com/product/ps5-pro-%EC%BD%98%EC%86%94-2tb-%EC%88%9C%EC%B0%A8%EC%B6%9C%EA%B3%A0/426/category/23/display/1/ | 공개 정형 데이터로 품절 확인 |

플레이샵 직접 상품 감시 워크플로는 요청에 따라 삭제했습니다. **G마켓은 요청에 따라 직접 조회를 완전히 제외했습니다.** GitHub 실행환경에서 HTTP 403이 확인됐으며, G마켓 이름이 포함된 공개 판매 공지·핫딜·커뮤니티 게시글을 발견하면 텔레그램 알림을 보내는 방식만 사용합니다. 이는 실제 재고 확인이 아니며 검색 색인 반영이 늦거나 누락될 수 있습니다.

## 알림 정확도

- 정형 상품 데이터에서 명확히 `InStock`이 확인되고 품명·정가·통화가 조건에 맞으면 **재고 감지** 알림.
- 기존 품절 표시가 사라졌다면 **확인 필요** 알림. 이것은 실제 재고 보장이 아닙니다.
- 직접 감시 대상 4곳에서 접근 오류가 발생하면 **감시 장애**로 구분해 상태 변경 시 알림. G마켓은 직접 조회하지 않으므로 장애 알림도 보내지 않음.
- RSS에 새 상품 판매 공지가 나오면 **판매 정보 확인 필요** 알림. 제목에 PS5 Pro가 있어도 실제 판매 여부를 보장하지 않습니다.
- 검색 색인 지연, 실행 대기, 판매처 제한, 페이지 구조 변경이 존재하므로 **실시간·30초 이내 도착·전체 매물 감지를 보장하지 않습니다.**

테스트: `python3 -m unittest test_retail_watch.py test_promo_watch.py -v`.

GitHub 상태 기록: `retail_state.json` / `promo_seen.json`. 불명 상태의 판매처는 계속 검증이 필요합니다.
