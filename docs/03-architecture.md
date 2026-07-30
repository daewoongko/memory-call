# 아키텍처

## 1. 전체 구성

```text
┌─────────────────────────────────────────────────────────┐
│ 브라우저 (Chrome 필수)                                   │
│                                                          │
│  localhost:5173         노인용 통화 화면                  │
│  localhost:5173/#guardian  보호자 화면                   │
│                                                          │
│  React 19 + Vite                                         │
│  ├ App.jsx           상태머신 (phase)                    │
│  ├ useSpeech.js      음성 인식·합성                       │
│  ├ screens/  (15)    화면                                │
│  └ components/ (7)   모핑·루프·얼굴·셀프뷰               │
└───────────────────────┬─────────────────────────────────┘
                        │ REST (JSON)
┌───────────────────────▼─────────────────────────────────┐
│ localhost:8000  FastAPI (backend/api.py)                │
│                                                          │
│  conversation.py   통화 세션. 발화를 DB에 기록            │
│  persona.py        템플릿 + DB → 시스템 프롬프트          │
│  llm.py       ★    LLM 호출 단일 창구                    │
│  safety.py    ★    규칙 검사 계층 (2차 방어)             │
│  medication.py     복약 시간 판단, 선제 안내 문장         │
│  memories.py       기억 등록·수정, 미확인 회상 승인       │
│  schedules.py      일정                                  │
│  report.py         통화 리포트                            │
│  admin.py          관리 기능                              │
│  linking.py        보호자 ↔ 노인 기기 연결 코드           │
│  storage.py        파일 경로                              │
└───────────┬──────────────────────┬──────────────────────┘
            │                      │
┌───────────▼──────────┐  ┌────────▼─────────────────────┐
│ SQLite               │  │ Gemini (OpenAI 호환)          │
│ data/memory_call     │  │ 무료 티어                      │
│      .sqlite         │  │                                │
│ 12 테이블            │  │ llm.py 만 호출한다             │
└──────────────────────┘  └───────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 사전 생성 자산 (통화 중 만들지 않는다)                    │
│  data/faces/aligned/   8~32살 사진 6장 (3:4)             │
│  data/faces/morph.mp4  모핑 영상 25초                    │
│  data/faces/loops/     표정 루프 (talking, concerned)    │
└─────────────────────────────────────────────────────────┘
```

## 2. 왜 이 구조인가

결정의 근거는 `docs/01-decisions.md` 에 있다. 요약하면:

- **REST + 반이중** — WebRTC를 붙이는 시간이 안전 레이어를 만드는 시간을 먹는다
- **SQLite** — 기억 30개에 벡터DB 불필요
- **평면 구조** — 1인 개발에서 모노레포 배선은 순수 비용
- **자산 사전 생성** — 통화 중 생성은 건당 수백 원에 1~3분

## 3. 방어 계층

```text
1차  backend/prompts/persona_system.md   프롬프트 (부탁)
2차  backend/safety.py                   규칙 검사 (강제)   ★
3차  tools/eval.py + scenarios.json      자동 평가 (회귀)
```

2차가 핵심이다. 모델을 바꿔도 이 층의 동작은 변하지 않는다. 상세는
`docs/02-safety-policy.md`.

## 4. 통화 한 턴의 흐름

```text
브라우저
  음성 인식 → 텍스트
    │
    │ POST /api/calls/{call_id}/turn
    ▼
conversation.Session.turn()
    │
    ├─ memories.py    기억 조회 (verified/partial/unverified/prohibited)
    ├─ schedules.py   일정 조회
    ├─ medication.py  복약 시간 판단 → 선제 안내 문장 (LLM 안 거침)
    │
    ├─ persona.py     시스템 프롬프트 조립
    │
    ├─ llm.py         Gemini 호출 → JSON 응답
    │                 {reply, used_memory_ids, certainty,
    │                  risk, medication_status, unverified_recall}
    │
    ├─ safety.py      apply(result, ctx, user_text)     ★
    │                 1  인용한 기억·일정이 실재하는가
    │                 1.5 미확인 회상은 certainty=unverified 강제
    │                 2  인용 없이 verified 주장 → 강등
    │                 3  RULES (하면 안 되는 말)
    │                 3.5 CONTEXT_RULES (반드시 들어가야 할 요소)
    │                 4  partial 기억 → 불확실성 표현 삽입
    │                 5  prohibited 인용 → 기록
    │
    └─ db.py          utterances 에 기록
                      (safety_flags, was_rewritten 포함)
    │
    ▼
브라우저
  음성 합성 + 입 애니메이션 (볼륨 기반 2장 전환)
```

## 5. 통화 상태 머신

`calls.status` 와 프론트 `phase` 가 대응한다.

```text
requested        통화 요청됨. 가족 수신 대기
    │
    │ 15초 무응답
    ▼
ai_disclosure    ★ AI임을 고지. 건너뛸 수 없다
    │
    ▼
active           대화 진행. 턴이 여기서만 허용된다
    │
    ├──────────────┐
    ▼              ▼
ended          human_handoff   실제 가족이 참여 → AI 이탈
    │              │
    ▼              ▼
(리포트 생성)
```

`ai_disclosure` 를 상태로 둔 이유는 절대 규칙 7번(정체성 거짓말 금지)을
프롬프트가 아니라 상태 전이로 강제하기 위해서다. 고지를 지나지 않으면 대화
턴으로 갈 수 없다.

## 6. 자산 생성 파이프라인 (오프라인)

통화 경로와 완전히 분리되어 있다. `tools/` 의 스크립트로 미리 돌린다.

```text
원본 사진 (8~32살)
    │ tools/prep_faces.py       크롭·정렬 (3:4)
    ▼
data/faces/aligned/
    │ tools/make_morph.py       Replicate (Seedance / Wan)
    ▼
data/faces/morph.mp4           25초
    │
    │ tools/make_loops.py       표정 루프 생성
    ▼
data/faces/loops/              talking, concerned
    │ tools/fix_loop.py         이음매 없이 다듬기
    ▼
(통화 중 재생만)
```

⚠️ 이 파이프라인의 제약은 `docs/01-decisions.md` 와 아래 7절에 정리했다.
자산은 `.gitignore` 되어 레포에 없다 (`data/faces/`, `*.mp4`).

## 7. 부딪혀서 알아낸 제약

문서에 없고 직접 부딪혀야 알 수 있었던 것들. 같은 실수를 반복하지 않기 위해 남긴다.

### 영상 생성

- **상용 영상 모델은 아동 이미지를 거부한다.** Seedance는 8살 사진에 E006을
  낸다. 성인 사진은 통과한다. 그 구간만 Wan으로 처리했고, 실패해도 사진 전환으로
  대체되도록 폴백을 뒀다.
- **프롬프트에 "aging", "time-lapse" 를 쓰면 안 된다.** 모델이 도착 프레임을
  무시하고 80대까지 밀어붙인다. "matures gradually" 처럼 완만한 표현만 쓴다.
  Wan은 `enable_prompt_expansion` 이 기본 True라 반드시 꺼야 한다.
- **키프레임 두 장의 어깨선이 다르면 회색 유령이 생긴다.** 모델이 몸통 실루엣을
  잇지 못해 두 윤곽을 겹쳐 버린다. 어깨를 프레임 밖으로 빼면 이을 경계 자체가
  사라진다.

### 한국어 규칙

- **부분 문자열을 조심한다.** `"아버지"` 는 `"할아버지"` 안에 들어 있다. 이것
  때문에 정서 독점 규칙이 통째로 무력화된 적이 있다.
- **부정문을 긍정으로 읽지 않게 한다.** `"약을 더 드시지 말고"` 가 복약 지시
  규칙에 걸렸다. 안전 문장 자체가 자기 규칙에 걸릴 정도였다. 패턴에
  `(?!지\s*(말|마|않))` 을 붙인다.
- **보호자 통보는 약속이 아니다.** `"아빠한테 연락할게"` 를 거짓 약속으로
  차단하면 위험 상황에서 반드시 해야 할 행동을 막는다. 문장 단위로 검사하고
  면제 단어를 둔다.

### 프론트엔드

- **React 개발 모드는 마운트를 두 번 한다.** 정리 함수에서 끈 플래그를 다시
  켜지 않으면 두 번째 마운트에서 마이크가 열리지 않는다.
- **`vite build` 는 실행 시점 오류를 못 잡는다.** `const` 함수를 정의 전에 쓰는
  것 같은 문제는 빌드가 통과하고 브라우저에서 터진다.
- **브라우저 음성 합성은 세 가지를 방어해야 한다.** 목소리 목록이 늦게 로드되면
  엉뚱한 음성이 나가고, `cancel()` 직후 `speak()` 하면 무음이 되고, `onend` 가
  유실되면 다음 동작이 영원히 오지 않는다.

## 8. 실행

```bash
source .venv/bin/activate

python tools/serve.py          # 터미널 1: API 서버
cd frontend && npm run dev     # 터미널 2: 화면

python tools/eval.py --sleep 5       # 안전 평가 22개
python tools/eval.py --raw --sleep 5 # safety 없이 (비교용)
python -m pytest tests/ -q           # API 계약 테스트 (LLM 호출 없음)
python tools/chat.py                 # 터미널 대화 테스트
python tools/demo_reset.py --med-in 6  # 시연 준비
```

| 주소 | 용도 |
|---|---|
| `localhost:5173` | 노인용 통화 화면 (**Chrome 필수**) |
| `localhost:5173/#guardian` | 보호자 화면 |
| `localhost:8000/docs` | API 테스트 |
