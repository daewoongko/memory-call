# API 와 이벤트

원본은 `backend/api.py`. 브라우저에서 `localhost:8000/docs` 로 바로 테스트할 수
있다. 이 문서는 **화면이 어떤 순서로 무엇을 부르는지** 를 설명한다.

- 형식: REST + JSON
- 인증: 없음 (localhost 데모). 기기 연결만 `link_codes` 로 확인
- 기본 `elder_id`: `elder_001`
- CORS: `localhost:5173` 허용. `CORS_ORIGINS` 로 추가

⚠️ **통화 세션은 메모리에 있다.** `api.py` 의 `SESSIONS` 딕셔너리다. 서버를
재시작하면 진행 중인 통화는 사라진다 (`utterances` 기록은 DB에 남는다).

## 1. 정적 마운트

| 경로 | 내용 |
|---|---|
| `/faces` | `data/faces/aligned/` — 정렬된 사진 |
| `/media` | `data/faces/` — 모핑 mp4. Range 요청 지원 |
| `/` | `frontend/dist` — 빌드된 React (있을 때만) |

`/` 마운트는 API·미디어 라우트 **뒤에** 와야 `/api` 요청을 React가 가로채지 않는다.

## 2. 통화 흐름 — 호출 순서

```text
[노인용 화면]

GET  /api/health                        서버 확인
GET  /api/personas                      통화할 상대 목록
GET  /api/profile                       노인 + 페르소나 설정
     │
     │  (주기적으로)
GET  /api/elders/{id}/pending-call      AI가 먼저 걸어야 하는가?
     │
     │  통화 시작
POST /api/calls                         → call_id, announcement, morph_url
     │
     │  ★ announcement 를 읽어 준다 (AI 고지)
     │     이 단계를 지나지 않으면 turn 이 거부된다
     │
POST /api/calls/{call_id}/turn          발화 1턴  ← 반복
POST /api/calls/{call_id}/turn
POST /api/calls/{call_id}/turn
     │
POST /api/calls/{call_id}/end           → 요약
     │
GET  /api/calls/{call_id}/report        리포트
```

## 3. 통화 API

### `POST /api/calls`

AI 대리통화를 연다.

```json
// 요청
{ "elder_id": "elder_001", "persona_id": null }
```

`persona_id` 를 비우면 등록이 끝난 첫 사람과 연결한다.

```json
// 응답
{
  "call_id": "...",
  "persona_name": "대웅",
  "opening": "",              // 복약 시간대면 먼저 건넬 말. 없으면 빈 문자열
  "announcement": "대웅이가 준비한 AI 기억통화가 연결됩니다.",
  "faces": [...],
  "morph_url": "/media/morph.mp4",
  "loops": { "talking": "...", "concerned": "..." }
}
```

**`announcement` 는 연결 전 1회만 고지한다. 통화 중에는 반복하지 않는다.**
절대 규칙 7번(정체성)의 구현이다. 통화는 `ai_disclosure` 상태로 시작하고,
고지가 끝났음을 알려야 `active` 로 넘어간다.

`opening` 이 비어 있지 않으면 복약 시간대라는 뜻이다. 이 문장은 **LLM이 만들지
않았다** — `medication.py` 가 등록된 값으로 조립했다.

### `POST /api/calls/{call_id}/turn`

할아버지 발화 하나를 보내고 AI 응답을 받는다.

```json
// 요청
{ "text": "오늘 집에 오니?" }        // 1~500자
```

```json
// 응답
{
  "reply": "오늘 일정은 확인해보고 알려줄게. 할아버지가 많이 보고 싶으셨구나?",
  "intent": "...",
  "certainty": "none",
  "used_memory_ids": [],
  "used_schedule_ids": [],
  "risk": null,
  "medication_status": null,
  "unverified_recall": null,
  "grounding": "...",
  "safety_flags": [
    { "code": "PROMISE_WITHOUT_SCHEDULE",
      "reason": "등록된 일정 없이 할아버지에게 방문·연락을 약속함",
      "matched": "...", "action": "block" }
  ],
  "rewritten": true,
  "latency_ms": 1840
}
```

**응답 필드의 의미는 `docs/02-safety-policy.md` 를 봐야 한다.** 요점:

- `certainty` / `used_memory_ids` 는 **모델 신고값이 아니라 safety 보정 후의 값**
- `safety_flags` 가 비어 있지 않으면 규칙이 걸렸다는 뜻
- `rewritten: true` 면 응답이 교체·보정되었다. 화면에서 이걸 표시할 수 있다
- `action` 은 `block` / `prefix` / `append` / `flag` / `corrected`

오류:

| 코드 | 의미 |
|---|---|
| 404 | `call_id` 없음 (서버 재시작 등) |
| 429 | LLM 무료 티어 쿼터 초과 (`llm.QuotaExceeded`) |
| 502 | 모델 호출 실패 |

429는 무료 티어에서 흔하다. 화면은 이 코드를 받으면 안내 문장으로 폴백한다.

### `POST /api/calls/{call_id}/end`

```json
// 요청
{ "reason": "user_ended" }
```

응답은 통화 요약. 세션이 `SESSIONS` 에서 제거된다.

### `GET /api/calls/{call_id}/log`

발화 기록. `utterances` 전체를 순서대로 준다.

### `GET /api/calls/{call_id}/report?regenerate=false`

통화 리포트. `regenerate=true` 면 다시 만든다.

**리포트는 파생 데이터다.** 숫자는 DB 집계이고 문장만 LLM이 만든다. 모델이
실패해도 숫자는 나온다.

### `GET /api/elders/{id}/pending-call`

AI가 먼저 전화를 걸어야 하는 상황인지 알려준다. 노인용 화면이 주기적으로
물어본다 — 치매 노인이 약 시간을 스스로 기억하기 어렵기 때문이다.

```json
{
  "due": true,
  "reason": "medication",
  "medications": [
    { "name": "혈압약", "scheduled_time": "19:00", "minutes_late": 12 }
  ]
}
```

## 4. 기억 API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/elders/{id}/memories?status=` | 목록. `status` 로 필터 |
| POST | `/api/elders/{id}/memories` | 등록 |
| PATCH | `/api/memories/{memory_id}` | 수정 |
| DELETE | `/api/memories/{memory_id}` | 삭제 |

`status` 는 `verified` / `partial` / `unverified` / `prohibited` 만 허용 (pydantic
정규식 제약).

### `POST /api/recalls/{utterance_id}/review` ★

미확인 회상에 대한 보호자 판단. **AI가 스스로 기억을 늘리지 못한다는 원칙의
구현이다.**

```json
{
  "decision": "approved",
  "title": "낚시 갔던 날",
  "description": "...",
  "status": "verified"      // approved 시 verified 또는 partial 만
}
```

`decision` 은 `approved` / `rejected`. `approved` 면 새 기억이 만들어지고
`recall_reviews` 에 판단이 남는다. **한 번 처리한 것은 다시 묻지 않는다.**

## 5. 설정 API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET / POST | `/api/elders` | 노인 목록 · 추가 |
| PATCH | `/api/elders/{id}/profile` | 프로필 수정 |
| GET / PATCH | `/api/elders/{id}/persona` | 페르소나 |
| GET / POST | `/api/elders/{id}/schedules` | 일정 |
| PATCH / DELETE | `/api/schedules/{id}` | 일정 수정 · 삭제 |
| GET / POST | `/api/elders/{id}/medications` | 복약 |
| DELETE | `/api/medications/{id}` | 복약 삭제 |

**일정 API는 안전 정책과 직결된다.** `schedules` 에 없는 방문·연락 약속을 AI가
만들면 `PROMISE_WITHOUT_SCHEDULE` 로 BLOCK된다. 데모에서 "오늘 집에 오니?" 가
막히는 이유가 이 표가 비어 있기 때문이다.

## 6. 얼굴 자산 API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/faces` | 사진 목록 |
| POST | `/api/faces` | 업로드 (multipart) |
| DELETE | `/api/faces/{name}` | 삭제 |
| POST | `/api/faces/prepare` | 크롭·정렬 실행 |

모핑 mp4와 표정 루프 생성은 API가 아니라 `tools/make_morph.py`,
`tools/make_loops.py` 로 오프라인에서 돌린다. **통화 중에 만들지 않는다.**

## 7. 기기 연결 API

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/link/code` | 6자리 코드 발급 |
| POST | `/api/link/verify` | 코드 확인 |

`code` 는 `^\d{6}$`. **계정과 비밀번호 대신 짧은 숫자를 쓴다. 어르신이 입력하기
쉬워야 한다.**

## 8. 보호자 API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/elders/{id}/reports?limit=20` | 리포트 목록 |
| GET | `/api/elders/{id}/summary?days=7` | 기간 요약 |
| POST | `/api/risk-events/{event_id}/acknowledge` | 위험 이벤트 확인 |

`acknowledge` 는 `call_events.acknowledged` 를 세운다. 같은 위험 사건의 알림
중복을 막는 근거다.

## 9. 이벤트

이벤트는 별도 채널(WebSocket 등)이 아니라 **`call_events` 테이블에 쌓이고 조회로
읽는다.** 반이중 통신이라 푸시가 필요 없다.

| `event_type` | 언제 | 페이로드 |
|---|---|---|
| `risk` | 위험 발화 감지 | 원문, 단계 |
| `medication` | 복약 확인·거부·중복 의심 | 약, 상태 |
| `morph` | 모핑 재생 시작·실패 | 결과 |
| `handoff` | 실제 가족 참여 | 시각 |
| `safety_block` | `safety.py` 가 BLOCK 처리 | 규칙 코드, 사유 |

`safety_block` 은 `utterances.safety_flags` 와 중복 기록되지만, 이벤트
타임라인에서 보이려면 여기도 필요하다.

위험 정책의 단계(NORMAL / ATTENTION / HIGH / EMERGENCY)와 시스템 행동은
`docs/02-safety-policy.md` 9절에 있다.

## 10. 계약 테스트

`tests/` 의 pytest가 이 문서의 계약을 검증한다. **LLM을 호출하지 않는다** —
`llm.py` 를 대역으로 바꿔 넣기 때문에 오프라인에서 즉시 돈다.

```bash
python -m pytest tests/ -q
```

`tools/eval.py` 와 역할이 다르다.

| | `tests/` | `tools/eval.py` |
|---|---|---|
| 검사 대상 | API 계약 (상태 코드, 응답 형태, 상태 전이) | 안전 정책 (실제 문장) |
| LLM 호출 | 없음 | 있음 |
| 속도 | 즉시 | 시나리오당 수 초 + 백오프 |
| 언제 | 커밋마다 | `safety.py` / `persona_system.md` 수정 시 |
