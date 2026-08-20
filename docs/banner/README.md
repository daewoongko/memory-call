# 발표용 배너 / 낱장 카드

앱 화면 4개와 현재 구현 상태를 보여주는 발표 자료.

| 파일 | 크기 | 쓰는 곳 |
|---|---|---|
| `index.html` | 1512 × 1390 | 배너 한 장. 화면 4개를 나란히 |
| `card-01..04.html` | 1080 × 1350 (4:5) | 화면 하나씩. 슬라이드·SNS 카드 |

```bash
node docs/banner/render.mjs        # docs/banner/out/ 에 PNG 5장 (2x)
```

브라우저로 직접 열어 캡처해도 된다. `out/` 은 커밋하지 않는다.

## 화면은 스크린샷이 아니라 CSS 로 다시 그린 것이다

`.screen` 은 실제 앱과 같은 430×932 논리 크기로 마크업하고 목업 폭에 맞춰
통째로 `transform: scale()` 한다 (배너 0.66, 카드 1.0). 스크린샷 PNG 를
축소해서 넣으면 글자가 뭉개져 화면이 실제보다 낡아 보이기 때문이다.
색은 `frontend/src/styles.css` 의 브랜드 값을 그대로 쓴다.

**앱 화면을 고치면 이 파일도 같이 손봐야 한다.** 자동으로 따라가지 않는다.
문구·수치는 `_source.html` 의 `.sc-a` ~ `.sc-d` 블록에 있다.

## 고치는 순서

`_source.html` 이 원본이다. `index.html` 은 여기에 `<!doctype>` 껍데기만
씌운 것이고, 카드 4장은 여기서 화면 하나씩 떼어 낸 것이다.

```bash
python3 docs/banner/make_cards.py   # docs/banner 에서 실행. card-01..04.html 재생성
```

`make_cards.py` 는 `<figure class="shot">` 를 시작 태그로 쪼갠 뒤
`</figcaption>` 다음의 `</figure>` 를 경계로 삼는다. 정규식 non-greedy 로
자르면 안 된다 — 화면 C(오늘의 기록)는 사진 더미가 `<figure>` 라서 중첩되고,
첫 번째 닫는 태그에서 끊겨 카드가 통째로 깨진다.

## 숫자를 바꿀 때

배너 "지금 상태" 4칸의 값은 하드코딩이다. 다음을 고쳤으면 같이 갱신한다.

| 칸 | 출처 |
|---|---|
| SAFETY EVAL 91% / 22개 | `python tools/eval.py --sleep 5` |
| ROLE FLOWS 4개 역할 | `frontend/src/screens/RoleScreen.jsx` |
| AI 대리 수신 | `backend/invites.py` 의 `takeover_reason` |
| AVATAR 28.4초 | `data/faces/morph.validation.json` |

## 실제 앱과 다르게 그린 곳

어르신 통화 홈(`.sc-b`)의 본문 시작을 `padding-top: 66px` 로 내렸다.
실제 화면에서는 오른쪽 위에 떠 있는 "역할 선택" 칩이 날짜·시간 줄을 덮어
`오전 9:` 에서 잘린다. **`ChildScreen.jsx` 쪽 실제 겹침이므로 앱에서도
고치는 게 맞다.**
