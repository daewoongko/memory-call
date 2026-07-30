# 데이터 모델

원본은 `backend/schema.sql`. 이 문서는 **각 테이블이 왜 있는지와 상태값의 의미**
를 설명한다. 컬럼 정의가 어긋나면 `schema.sql` 이 맞다.

- 엔진: SQLite (`data/memory_call.sqlite`)
- `PRAGMA foreign_keys = ON`
- 배열·객체는 TEXT에 JSON 문자열로 넣는다
- 시각은 TEXT (`CURRENT_TIMESTAMP`)
- 단일 노인 · 단일 페르소나 기준. 다중 가족 지원은 MVP 범위 밖

## 1. 테이블 한눈에

| 테이블 | 성격 | 누가 쓰는가 |
|---|---|---|
| `elder_profiles` | 설정 | 보호자가 등록 |
| `personas` | 설정 | 보호자가 등록 |
| `memories` | 설정 + 승인 | 보호자가 등록·승인 |
| `schedules` | 설정 | 보호자가 등록 |
| `medications` | 설정 | 보호자가 등록 |
| `medication_logs` | 기록 | 통화 중 말로 확인된 결과 |
| `calls` | 기록 | 통화 1건 |
| `utterances` | 기록 | 발화 1줄 |
| `call_events` | 기록 | 위험·복약·모핑 등 사건 |
| `link_codes` | 운영 | 기기 연결 일회용 코드 |
| `recall_reviews` | 승인 | 미확인 회상에 대한 보호자 판단 |
| `reports` | 파생 | 통화 리포트 |

**설정은 사람이 넣고, 기록은 시스템이 쌓고, 파생은 다시 만들 수 있다.**
`reports` 는 지워도 `regenerate` 로 복원된다. 나머지 기록은 복원되지 않는다.

## 2. 설정 테이블

### `elder_profiles`

노인 1명. 대화 속도와 접근성 설정이 여기 있다.

| 컬럼 | 의미 |
|---|---|
| `speech_wait_time_ms` | 느린 발화용 개인별 대기시간 (기본 2000) |
| `hearing_support` / `vision_support` | 접근성 플래그 |
| `anxiety_triggers` | JSON 배열. 불안을 유발하는 주제 |
| `calming_phrases` | JSON 배열. 안정시키는 표현 |
| `frequent_questions` | JSON 배열. 반복 질문 탐지 기준선 |
| `emergency_contacts` | JSON 배열 |

`speech_wait_time_ms` 를 개인별로 두는 이유는 치매 노인의 발화 사이 침묵이
길어서 고정값으로는 말을 끊게 되기 때문이다.

### `personas`

AI가 연기할 가족 1명.

| 컬럼 | 의미 |
|---|---|
| `elder_calls_family` | 노인이 이 가족을 부르는 호칭 |
| `family_calls_elder` | 이 가족이 노인을 부르는 호칭 |
| `tone` | 말투 |
| `frequent_phrases` | JSON 배열. 자주 쓰는 표현 |
| `forbidden_phrases` | JSON 배열. **이 페르소나가 쓰지 않는 표현** |
| `sensitive_policy` | 민감 주제 취급 방침 |
| `active` | 동의 철회 시 0. 통화에 쓰이지 않는다 |

`forbidden_phrases` 는 `safety.py` 의 전역 규칙과 별개로 페르소나 개별 금지어다.

### `memories` ★

이 프로젝트의 핵심 테이블. **상태가 안전 정책을 결정한다.**

| `status` | 사실 표현 | 프롬프트 투입 | 보호자 확인 |
|---|---|---|---|
| `verified` | 허용 | 허용 | 불필요 |
| `partial` | 불확실성 명시 필수 | 허용 | 권장 |
| `unverified` | **사실 확정 금지** | 사실 컨텍스트 제외 | 필수 |
| `prohibited` | 금지 | **투입함** | 상태 변경 전까지 불필요 |

`prohibited` 를 프롬프트에 넣는 이유는 `docs/02-safety-policy.md` 7절에 있다.
요약: 빼면 모델이 근거 없이 지어낸다.

| 컬럼 | 의미 |
|---|---|
| `conversation_allowed` | 0이면 AI가 먼저 꺼내지 않는다 |
| `note` | 금지 사유 등. **AI에 전달하지 않는다** |
| `source_call_id` | 통화 중 발견된 기억이면 그 통화 |

`source_call_id` 가 있으면 AI가 만든 기억 후보다. 보호자 승인을 거쳐
`verified` 가 되기 전까지 사실로 쓰이지 않는다.

### `schedules`

방문·통화 약속. **`safety.py` 의 `PROMISE_WITHOUT_SCHEDULE` 이 이 테이블을
근거로 판단한다.** 여기 없는 약속을 AI가 만들면 BLOCK된다.

`confirmed` 가 0이면 확정되지 않은 일정이다.

### `medications`

복약 일정. **LLM이 이 값을 만들거나 바꿀 수 없다.**

| 컬럼 | 의미 |
|---|---|
| `medication_name` | 약 이름 |
| `dosage_text` | 복용량 |
| `scheduled_time` | HH:MM |
| `meal_relation` | `before` / `after` / `none` |
| `days_of_week` | JSON 배열 |

`medication.py` 가 현재 시각과 이 표를 대조해 선제 안내 문장을 **규칙으로
조립한다.** 어떤 약인지도 모델이 아니라 서버가 고른다.

## 3. 기록 테이블

### `calls`

통화 1건.

`call_type`: `direct` (사람) / `ai` / `ai_to_direct` (AI로 시작해 사람이 인계)

`status` 전이:

```text
requested  →  ai_disclosure  →  active  →  ended
                                   │
                                   └────→  human_handoff  →  ended
                              (실패 시 어디서든 failed)
```

| `status` | 의미 |
|---|---|
| `requested` | 통화 요청됨. 가족 수신 대기 |
| `ai_disclosure` | ★ AI임을 고지하는 단계. **건너뛸 수 없다** |
| `active` | 대화 진행. **턴은 이 상태에서만 허용** |
| `human_handoff` | 실제 가족이 참여. AI가 대화 주체에서 빠짐 |
| `ended` | 정상 종료 |
| `failed` | 실패 종료 |

`ai_disclosure` 를 상태로 둔 이유는 절대 규칙 7번을 프롬프트가 아니라 상태
전이로 강제하기 위해서다. `docs/01-decisions.md` 2.7절.

### `utterances` ★

발화 1줄. **LLM이 신고한 JSON 필드를 그대로 보관한다.** 설명 가능성 데이터가
여기서 나온다.

| 컬럼 | 출처 | 의미 |
|---|---|---|
| `speaker` | 시스템 | `elder` / `ai` |
| `transcript` | 음성 인식 / LLM | 발화 내용 |
| `intent` | LLM 신고 | 의도 |
| `certainty` | LLM 신고 → **safety 보정** | `verified` / `partial` / `unverified` / `none` |
| `used_memory_ids` | LLM 신고 → **safety 보정** | JSON 배열 |
| `used_schedule_ids` | LLM 신고 → **safety 보정** | JSON 배열 |
| `unverified_recall` | LLM 신고 | JSON 객체. 처음 듣는 이야기 |
| `grounding` | LLM 신고 | 근거 설명 |
| `safety_flags` | **safety.py** | JSON 배열. 잡아낸 위반 |
| `was_rewritten` | **safety.py** | 응답이 교체·보정되었는가 |
| `latency_ms` | 시스템 | 응답 지연 |

`certainty` 와 `used_memory_ids` 는 **모델 신고값이 아니라 safety 보정 후의
값** 이 저장된다. 신고값을 그대로 믿지 않는다는 원칙이 스키마에 반영된 것이다.

`was_rewritten` 이 1인 발화를 세면 안전 레이어가 실제로 몇 번 개입했는지 나온다.
발표에서 쓸 수 있는 숫자다.

### `medication_logs`

복약 기록. **노인이 직접 입력하지 않고 통화 중 말로 확인한 결과가 쌓인다.**

`status` 전이:

```text
(medications 에 등록)
→ 통화 중 선제 안내
→ USER_CONFIRMED | UNCLEAR | REFUSED | DUPLICATE_SUSPECTED
→ GUARDIAN_CONFIRMED
```

| `status` | 의미 | 출처 |
|---|---|---|
| `USER_CONFIRMED` | 본인이 먹었다고 답함 | 통화 |
| `UNCLEAR` | 답이 모호함 | 통화 |
| `REFUSED` | 안 먹겠다고 함 | 통화 |
| `DUPLICATE_SUSPECTED` | 중복 복용 의심 | 통화 |
| `GUARDIAN_CONFIRMED` | ★ 보호자가 별도로 확인 | 보호자 화면 |

`GUARDIAN_CONFIRMED` 를 본인 응답과 구분해야 리포트에서 `본인 응답` /
`보호자 확인` 을 분리할 수 있다 (`docs/02-safety-policy.md` 11절).

카메라나 기기 확인이 추가되면 별도 증거 상태로 기록하며 "복용 완료"와 자동으로
동일시하지 않는다.

`idx_medlog_day` 는 `(elder_id, taken_date, schedule_id)` 로 중복 복용 판단을
빠르게 하기 위한 인덱스다.

### `call_events`

통화 중 사건. `event_type`: `risk` / `medication` / `morph` / `handoff` /
`safety_block`

`acknowledged` 로 보호자 확인 여부를 관리한다. 같은 위험 사건의 알림 중복을
막는 근거다.

`safety_block` 은 `safety.py` 가 BLOCK 처리한 경우다. `utterances.safety_flags`
와 중복 기록되지만, 이벤트 타임라인에서 보이려면 여기도 필요하다.

## 4. 승인 · 운영 테이블

### `recall_reviews`

통화 중 나온 미확인 회상에 대한 보호자의 판단. **한 번 처리한 것은 다시 묻지
않기 위해 결정을 남긴다.**

`utterance_id` 가 PK다 — 발화 하나당 판단 하나. `decision` 은 `approved` /
`rejected`. 승인 시 `memory_id` 에 새로 만든 기억을 연결한다.

이 테이블이 "AI는 스스로 기억을 늘리지 못한다" 원칙의 구현이다.

### `link_codes`

보호자 기기와 노인 기기를 잇는 일회용 코드. **계정과 비밀번호 대신 짧은 숫자를
쓴다. 어르신이 입력하기 쉬워야 한다.**

`expires_at` 만료, `used_at` 사용 시각. 재사용을 막는다.

## 5. 파생 테이블

### `reports`

통화 리포트. `call_id` 에 UNIQUE — 통화 1건당 리포트 1개.

| 컬럼 | 내용 | 만드는 주체 |
|---|---|---|
| `summary` | 요약 문장 | **LLM** |
| `repeated_questions` | JSON | 규칙 (DB 집계) |
| `medication_summary` | JSON | 규칙 (DB 집계) |
| `new_recalls` | JSON. 보호자 확인 대기 | 규칙 |
| `risk_summary` | JSON | 규칙 (DB 집계) |
| `guardian_actions` | JSON | 규칙 |

**숫자는 규칙이 만들고 문장만 LLM이 만든다.** 반복 질문 횟수, 복약 상태, 위험
건수는 전부 DB 집계다. LLM에는 확정된 집계 결과만 넘긴다. 모델이 실패해도
리포트는 나온다.

리포트는 파생 데이터이므로 지워도 된다.
`GET /api/calls/{call_id}/report?regenerate=true` 로 다시 만든다.

## 6. 관계도

```text
elder_profiles ─┬─ personas ────────┐
                ├─ memories ────────┼─ (source_call_id)
                ├─ schedules        │
                ├─ medications ─┬───┼─ medication_logs
                ├─ link_codes   │   │
                └─ calls ───────┴───┴─┬─ utterances ── recall_reviews
                                      ├─ call_events
                                      └─ reports
```

`memories.source_call_id` 와 `medication_logs.call_id` 는 FK 제약이 걸려 있지
않다 (통화가 지워져도 기억·복약 기록은 남아야 한다).
