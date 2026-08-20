# 발표용 배너

`index.html` 한 장으로 서비스 소개 + 현재 구현 상태를 보여준다.
브라우저로 열고 화면을 캡처하면 그대로 발표 자료에 넣을 수 있다.

```bash
python -m http.server 8080 -d docs/banner   # 또는 파일을 그냥 브라우저로 연다
```

## 안에 들어간 것

- 헤드 카피 + 안전 정책 한 줄 (이 프로젝트의 논점)
- 지금 상태 4칸 — eval 통과율 / 역할 흐름 / AI 대리 수신 / 아바타
- 화면 4개 — 역할 선택 → 어르신 통화 홈 → 오늘의 기록 → 보호자 분석 리포트

## 화면은 스크린샷이 아니라 CSS 로 다시 그린 것이다

`.screen` 은 실제 앱과 같은 430×932 논리 크기로 마크업하고 목업 폭에 맞춰
통째로 `transform: scale()` 한다. 스크린샷 PNG 를 축소해서 넣으면 글자가
뭉개져서 화면이 실제보다 낡아 보이기 때문이다. 색은 `frontend/src/styles.css`
의 브랜드 값을 그대로 쓴다.

**앱 화면을 고치면 이 파일도 같이 손봐야 한다.** 자동으로 따라가지 않는다.
문구·수치는 `--a-*` 토큰 아래 `.sc-a` ~ `.sc-d` 블록에 있다.

## 숫자를 바꿀 때

"지금 상태" 4칸의 값은 하드코딩이다. 다음을 고쳤으면 같이 갱신한다.

| 칸 | 출처 |
|---|---|
| SAFETY EVAL 91% / 22개 | `python tools/eval.py --sleep 5` |
| ROLE FLOWS 4개 역할 | `frontend/src/screens/RoleScreen.jsx` |
| AI 대리 수신 | `backend/invites.py` 의 `takeover_reason` |
| AVATAR 28.4초 | `data/faces/morph.validation.json` |
