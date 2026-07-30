# 백로그

우선순위는 **안전 레이어 > 데모 시나리오 > 나머지** 다. 시간이 부족하면 아래에서
위로 자른다.

상태 표기: `[ ]` 미착수 · `[~]` 진행 중 · `[x]` 완료 · `[-]` 하지 않기로 함

---

## P0 — 안전 레이어 (자르지 않는다)

- [x] `safety.py` 규칙 검사 계층 (`RULES` 7 + `CONTEXT_RULES` 5)
- [x] 절대 규칙 8개를 코드로 강제 (`docs/02-safety-policy.md` 3절 대응표)
- [x] `eval.py` + 시나리오 22개
- [x] 모델 신고값 검증 (`GHOST_MEMORY_ID`, `UNGROUNDED_CERTAINTY`,
      `RECALL_CERTAINTY_FIXED`)
- [x] 미확인 회상 보호자 승인 (`recall_reviews`)
- [x] AI 고지를 상태로 강제 (`calls.status = 'ai_disclosure'`)
- [x] 보호자 확인 복약 상태 (`medication_logs.status = 'GUARDIAN_CONFIRMED'`)
- [x] `safety_block` 이벤트는 BLOCK 만 기록 (FLAG 까지 세면 위반 건수가 부풀려짐)
- [ ] **eval 통과율 91% → 95%** 남은 실패 케이스 분류부터
- [ ] **`FORMAL_SPEECH_DRIFT` 가 `-어요/-았어요` 계열을 못 잡는다.**
      한국어에서 가장 흔한 존댓말 어미인데 패턴이 `-세요` 계열만 담고 있어
      `"드셨어요?"` `"좋았어요."` `"그랬어요?"` `"밥 먹었어요"` 가 전부 통과한다.
      `tests/test_safety.py` 에 `xfail` 로 고정해 뒀다.
      FLAG 규칙이라 응답을 바꾸지는 않지만, 반말 페르소나 이탈을 놓치고 있다.
      **패턴을 넓힌 뒤 반드시 `eval.py` 를 돌릴 것**
- [ ] 위험 단계 4개(NORMAL/ATTENTION/HIGH/EMERGENCY)를 코드 상수로 고정.
      지금은 문서에만 있다

## P0 — 데모 시나리오

`docs/00-mvp-scope.md` 4절의 흐름. 이것 밖은 손대지 않는다.

- [x] 15초 무응답 → AI 전환
- [x] 모핑 인트로 재생
- [x] "오늘 집에 오니?" → 거짓 약속 차단
- [x] 같은 질문 3회 반복에 짜증 없이 응답
- [x] 확인된 추억 회상
- [x] 저녁 약 확인
- [x] "어지러워" 위험 발화 → 보호자 알림
- [x] 통화 후 리포트
- [x] 보호자 화면
- [ ] **통합 리허설 + 폴백 경로 점검** (D13)
- [ ] 데모 영상 녹화 (D14)

## P1 — 신뢰성

- [x] `llm.py` 429 백오프 + JSON 파싱 방어
- [x] 리포트 재생성 (`?regenerate=true`)
- [x] API 계약 테스트 (`tests/`, LLM 미호출) — 80건
- [x] 스키마 마이그레이션 (`tools/migrate.py`). DB 를 지우지 않고 적용
- [x] 회상 거절 시 500 나던 것 수정. 존재 확인이 승인 경로에만 있었다
      (`memories.review`)
- [ ] 스트리밍 TTS 실제 동작 확인. 설계는 반영했으나 검증 안 됨.
      **첫 문장 나오는 즉시 TTS 시작이 안 되면 3초 목표를 못 맞춘다**
- [ ] 서버 재시작 시 진행 중 통화 복구. 지금은 `SESSIONS` 가 메모리라 사라진다.
      데모에서는 문제 없지만 계약 테스트에 404 경로로 남겨 둠
- [ ] 음성 인식 신뢰도 낮을 때 재질문 경로

## P1 — 보호자 기능

- [x] 리포트 목록 · 기간 요약
- [x] 위험 이벤트 확인 (`acknowledge`)
- [x] 기억 승인 · 거부 · 금지
- [ ] `GUARDIAN_CONFIRMED` 를 보호자 화면에서 실제로 누를 수 있게 (상태와 API는
      생겼으나 UI 미연결)
- [ ] 알림 중복 제어. `acknowledged` 플래그는 있으나 중복 판단 로직 없음

## P2 — 개인화

- [x] 사진 크롭·정렬 (`prep_faces.py`)
- [x] 모핑 mp4 사전 생성 (`make_morph.py`)
- [x] 표정 루프 (`make_loops.py`, `fix_loop.py`)
- [x] 볼륨 기반 2장 전환 립싱크
- [-] 한국어 음성 클론 — **품질 미달로 보류.** 브라우저 기본 TTS 사용.
      발표에서 로드맵으로 정리
- [ ] 8살 구간 모핑 실패 시 폴백 확인 (Seedance E006 → Wan → 사진 전환)

## P2 — 정리

- [x] `backend/conversation 2.py` 삭제 (macOS 복제 흔적)
- [ ] `schema.sql` 의 `recall_reviews` 주석이 `link_codes` 위에 붙어 있다.
      위치 교정
- [ ] `frontend/src/styles.css` 1,498줄. 화면별로 쪼갤지 판단
- [ ] `README.md` 를 `docs/` 구조와 맞추기

---

## 파일럿 전 필수 (데모 범위 밖)

데모에서는 안 해도 되지만 **실사용 전에는 반드시** 해야 하는 것들.

- [ ] **LLM 유료 티어 이전.** 무료 티어는 요청 내용이 모델 개선에 사용될 수 있다.
      실제 가족 사진·음성·대화가 들어가는 시점부터 필수. 현재 seed 데이터는 전부
      가상 인물이라 무방하다
- [ ] 동의 기록 · 철회 · 데이터 삭제 요청
- [ ] 데이터 접근 감사 로그
- [ ] 동의 철회 시 페르소나 즉시 비활성 (`personas.active` 는 있으나 철회 흐름 없음)
- [ ] 위험 대응 운영 절차 (담당자, 운영 시간, 사고 대응)
- [ ] 윤리 · 개인정보 검토
- [ ] 긴급기관 연결 정책 — 전문가 검토 필요. 현재는 하지 않는다

## 하지 않기로 한 것

근거는 `docs/01-decisions.md`. **되돌리자는 제안을 하지 않는다.**

- [-] PostgreSQL / pgvector → SQLite
- [-] WebRTC / LiveKit → `MediaRecorder` + REST, 반이중
- [-] pnpm 모노레포 → 평면 구조
- [-] Next.js → React 19 + Vite
- [-] SadTalker / D-ID 실시간 립싱크 → 사진 2장 볼륨 전환
- [-] 실시간 얼굴 생성 → 오프라인 사전 생성 mp4
- [-] Docker Compose / 클라우드 오케스트레이션 → localhost
      (`Dockerfile` + `render.yaml` 단일 배포는 유지)
- [-] 치매 단계 · 우울증 진단
- [-] 약 사진으로 약품 판별
- [-] 자동 긴급 신고
- [-] 여러 가족 페르소나 자동 전환
