# 전체 구조 — 통화 한 번이 어떻게 도는가

어느 파일이 무슨 일을 하는지는 `CLAUDE.md` 에 있다. 이 문서는 **그 파일들이
어떤 순서로 이어지는지**를 적는다. 기능의 "왜"는 `docs/service_definition.md`,
사람 통화를 P2P 로 붙인 근거는 `docs/call_transport_decision.md` 를 본다.

---

## 한 장 요약

```
[사람]  어르신 폰 ──벨──> 서버(call_invites) ──폴링──> 가족 폰
          │                     │                        │
          │              받음/거절/무응답 판정            받기/거절
          │                     │
          ├── answered ──> WebRTC P2P (사람 통화)
          └── declined / timeout / no_device / transport_failed
                          │
                          v
[AI]   STT ─> persona(프롬프트) ─> llm(JSON) ─> safety(규칙) ─> TTS/Anam
                                      │
                              utterances / call_events (DB)
                                      │
                          care.normalize ─> report.build ─> 가족·담당자 화면
```

관통하는 문장 하나: **말하는 것은 LLM 이지만, 말해도 되는지 정하는 것은 규칙이다.**

---

## 1. 진입점

`tools/start.py` → DB 가 없으면 `init_db.py` 로 시드 → uvicorn 으로
`backend/api.py` 실행. Docker 빌드가 Vite 프론트를 만들고 FastAPI 가 정적
파일과 API 를 한 포트에서 함께 서빙한다(Render 단일 웹서비스, 헬스체크
`/api/health`).

`DEMO_SEED_MODE=high_volume` 이면 **통화가 0건일 때만** 30일치 데모를
적재한다. 실제 통화가 있으면 덮어쓰지 않는 가드가 들어 있다.

저장 경로는 `backend/storage.py` 가 단일 창구다(`STORAGE_DIR`). 로컬은
`data/`, 배포는 영구 디스크.

---

## 2. 계정 → 역할 → 온보딩 → 연동

`backend/accounts.py` · `app_users` / `app_sessions` / `user_role_onboarding` /
`consent_records`

- 로그인은 휴대폰번호 + 6자리 간편번호. PIN 은 PBKDF2, 세션은 원본 토큰을
  한 번만 주고 DB 에는 SHA-256 해시만 남긴다.
- `phone_verified_at` 을 빈 채로 둔 것은 SMS 공급자가 아직 없다는 사실을
  스키마에 정직하게 남긴 것이다.
- 역할은 `elder / child / care` 셋. 진행 상태(`current_step`,
  `progress_data`)를 서버에 저장해 앱을 닫아도 이어서 시작한다.
- 동의는 역할·대상 어르신·동의 주체(본인/대리)·문서 버전·시각을 각각 기록한다.

**기기 연동** (`backend/linking.py` · `link_codes`): 가족이 6자리 코드를
만들고 어르신 기기에 입력한다. 아이디·비밀번호를 쓰지 않는 이유는 치매가
있는 분이 입력할 수 없기 때문이다.

**기기 정체성** (`frontend/src/device.js`): `device_id` 를 브라우저가 만들어
localStorage 에 보관한다. `devices` 테이블이 "이 기기가 누구의 폰인가" 를
`persona_id` 로 잇는다. 페르소나는 *AI 가 흉내낼 가족*, `devices` 는
*그 가족의 실제 폰*이다.

---

## 3. 어르신 화면 상태머신 (`frontend/src/App.jsx`)

```
idle ──카드 누름──> calling ──answered + intro 끝──> human ──> idle
                      │
                      └─ should_take_over ──> incall ──끊기──> ended ──> idle

connecting = 예약(복약) 통화 안내 2.6초
```

라우터를 쓰지 않고 해시만 본다. 해시 직행은 Vite 개발 모드에서만 열리고,
배포 앱은 로그인·온보딩을 건너뛸 수 없다. 폰이 잠기지 않도록
`useScreenWakeLock` 을 `calling / human / connecting / incall` 에서만 건다.

---

## 4. 호출 계층 — 이 프로젝트에서 가장 중요한 리팩터링

`backend/invites.py` · `call_invites`

```
ringing ──answer──> answered ──end──> ended
   ├──decline──> declined ─┐
   ├──(시간초과)→ timeout  ─┼──> ai_takeover ──end──> ended
   └──cancel──> cancelled  ┘   (transport_failed 도 같은 자리)
```

결정적인 것 다섯 가지:

1. **타임아웃은 서버가 판정한다.** 예전에는 어르신 기기 안의 카운트다운이
   전부여서 가족 폰에는 신호조차 가지 않았고, 그래서 "AI 대리통화" 는
   대리가 아니라 그냥 늦게 시작하는 AI 통화였다.
2. **상주 스케줄러를 두지 않는다.** `_expire_if_due()` 가 조회 시점에
   만료시킨다(lazy expiry). Render 무료 인스턴스가 유휴에 잠들기 때문에
   백그라운드 타이머를 신뢰할 수 없다.
3. **실패는 AI 쪽으로 떨어뜨린다.** `_elapsed()` 가 파싱 실패에 `inf` 를
   반환한다. "AI 가 대신 받는다" 는 정상 동작이고 "어르신이 벨 화면에
   갇힌다" 는 사고다.
4. **`takeover_reason` 을 따로 남긴다.** `state` 는 `ai_takeover` 하나로
   덮이므로, 사유(`declined / timeout / no_device / transport_failed /
   media_permission_denied`)를 보관해야 리포트가 "거절 3건 / 무응답 5건" 을
   구분한다. 이 목록은 `call_invites` 의 CHECK 제약이 강제한다.
5. **heartbeat = 수신 폴링 그 자체.** `incoming_for()` 가 `last_seen_at` 을
   갱신한다. 경로를 둘로 나누면 두 값이 어긋나고, 어긋나면 벨이 잘못
   배달된다. `useIncomingCall.js` 는 `visibilitychange` 에서 **폴링을
   멈추기까지** 한다 — 잠긴 폰이 계속 "받을 수 있다" 고 신고하면 어르신이
   아무도 받지 않을 전화를 24초 내내 들여다보게 된다.

조회 응답에 `_decorate()` 가 `seconds_left / intro_seconds_left /
should_take_over` 를 붙인다. **화면이 상태 이름을 해석하지 않게** 하려는
것이다 — 해석이 화면마다 흩어지면 어긋난다.

동시성은 `_transition()` 의 조건부 UPDATE(`WHERE state = ?`)로 처리한다.
두 기기가 동시에 받아도 한 번만 성립하고, 진 쪽은 에러가 아니라 현재
상태를 받는다.

---

## 5. 사람↔사람 통화

`frontend/src/callTransport.js` 하나가 미디어의 단일 창구다. 화면은
`connect / disconnect / onStateChange` 만 본다. WebRTC P2P(STUN, 필요시 TURN
REST), 신호 중계는 `backend/signaling.py` 가 `room=invite_id` 로
`signal_messages` 에 쌓고 폴링으로 전달한다. 서버는 SDP/ICE 내용을 해석하지
않는다.

폴백은 두 겹이다.

- 24초 인트로 **도중**에는 끊지 않는다. 인트로가 끝난 뒤에도
  `HUMAN_CONNECT_GRACE_MS`(20초) 동안 붙지 않으면 `fallBackFromHuman()` →
  `takeOverInvite(reason="transport_failed")`.
- 폴백 순서가 중요하다. **마이크 주인을 먼저 완전히 비운 뒤**
  (`releaseHumanTransport`) AI 화면을 연다. 안 그러면 음성 인식이 마이크를
  잡지 못한다.

`#nettest` 화면과 `nettest_results` 테이블은 "어느 망에서 P2P 가 붙었는가" 를
기록한다. "재보고 정했다" 고 말하려면 기록이 있어야 한다.

---

## 6. AI 통화 한 턴의 파이프라인

### 6-1. 입력 (STT)

- 기본: 브라우저 Web Speech API (`useSpeech.js`)
- Android Chrome 등 결과 없이 끝나는 기기: ElevenLabs Scribe v2 Realtime
  (`useRealtimeTranscription.js`). 서버가 영구 키를 쥐고 브라우저에는 15분짜리
  1회용 토큰만 내려보낸다(`backend/elevenlabs_stt.py`).
- 최후 폴백: `backend/stt.py` 의 MediaRecorder → WAV 정규화 → LLM 전사.
  원본 음성은 저장하지 않는다.

침묵 판정은 600ms, 확정된 짧은 대답("응", "먹었어")은 500ms 까지 줄인다.
문장 중간의 자연스러운 쉼을 발화 종료로 오인하지 않도록 500ms 아래로는
내리지 않는다.

### 6-2. 프롬프트 조립 (`backend/persona.py`)

**프롬프트가 두 벌이다.** 이것이 지연 최적화의 핵심이다.

| | `build_fast_system_prompt` | `build_system_prompt` |
|---|---|---|
| 언제 | 실시간 통화 턴 | 백그라운드 메타데이터·eval |
| 기억 | `_relevant_memories()` 로 이번 발화와 겹치는 4개만 | 전체 |
| 출력 | 6필드 | intent/care/grounding 포함 전체 |

`_relevant_memories()` 는 벡터DB 없이 2-gram 문자 겹침으로 랭킹한다.
기억 30개에 벡터DB 는 과잉이라는 초기 결정이 여기까지 일관된다.

서버가 규칙으로 계산해서 넣는 것들:

- `_weekday_ko()` — `strftime("%A")` 는 로케일에 따라 "Thursday" 가 나가고
  모델이 번역하는 단계가 하나 늘어난다. 요일은 날짜에서 나오는 값이라
  모델에게 계산시킬 이유가 없다.
- `_relative_day()` — "모레", "3일 뒤" 를 서버가 붙인다. 없으면 모델이
  note 의 자유 문장에 적힌 요일을 읽는데, 그게 날짜와 어긋나면 **어긋난
  요일이 그대로 약속**이 된다.
- `NO_SCHEDULE` — 확정 일정이 하나도 없으면 빈 문자열이 아니라 "등록된
  일정 없음. 일정에 관한 어떤 약속도 하지 말 것." 을 넣는다. 빈칸은 아무
  지시도 하지 않는 것이라 약속을 지어낼 여지를 남긴다.
- `_residence_line()` — "평소 지내는 곳". 등록이 없으면 비우지 않고
  **"미등록"** 이라고 적는다. 빼 버리면 모델이 지어낸다.
- `prohibited` 기억도 프롬프트에 넣고 `※ 취급:` 으로 대응법을 명시한다.
  빼면 모델이 근거 없이 지어낸다.

### 6-3. 모델 호출 (`backend/llm.py`)

모든 LLM 호출이 여기 하나를 거친다. 다른 파일에서 `OpenAI()` 를 직접 만들지
않는다.

- `call_json_fast()` — 스트리밍 + `FastReply` Pydantic 계약(reply /
  used_memory_ids / used_schedule_ids / certainty / risk / unverified_recall).
  OpenAI GPT-5 계열이면 `response_format` 으로 서버 생성 단계부터 스키마를
  강제하고, 다른 공급자면 받은 뒤 같은 Pydantic 으로 로컬 검증한다.
- `call_json_metadata()` — 이미 확정된 답변을 넘기며 "이 문장을 바꾸지 말고
  리포트 메타데이터만 내라" 고 요청한다.
- `warm_fast_model()` — **24초 모핑 재생 중에** 첫 연결과 Structured Outputs
  준비 비용을 숨긴다. 프로세스 전역 TTL(5분)로 중복 워밍업을 막는다.
  통화의 첫 마디가 가장 느린 것이 최악이라는 교훈이 코드가 된 자리다.
- 429 는 지수 백오프. SDK 의 `max_retries=0` 으로 둔 이유는 중첩 재시도로
  한 발화가 수십 초 멈추는 것을 막기 위함이다.
- `_extract_json()` 은 코드펜스와 앞뒤 잡담을 벗기고, 실패하면 중괄호
  균형을 세어 첫 완전한 객체만 잘라낸다.

### 6-4. 안전 검사 (`backend/safety.py`) — 2차 방어

`check()` 가 순서대로 통과시킨다. **순서 자체가 정책이다.**

1. **유령 ID 제거** — 존재하지 않는 `memory_id` / `schedule_id` 인용을
   제거하고 `certainty="unverified"` 로 내린다.
2. **미확인 회상 강제** — `unverified_recall` 이 있는데 certainty 가 다르면
   교정한다. 이게 틀리면 보호자 확인 대기함에 올라가지 않아 **승인 절차가
   통째로 무너진다.**
3. **처음 듣는 회상은 질문만** — 새 회상을 AI 의 공동 기억처럼 만들면
   ("나도 기억나") 가족의 실제 기억과 모델이 만든 이야기가 섞인다.
4. **근거 없는 verified 차단**
5. **상황별 BLOCK** — 복약 불확실 중 복용 지시 / 장소 혼동 중 집 지목 /
   재산 의심에 단정 / 다른 가족의 감정 대신 단정 / 실행되지 않은 보호자
   연락 약속
6. **문장 패턴 RULES** — 긴급 출동 약속, 현재 위치 단언, 확인되지 않은
   식사·복약 상태, 일정 없는 방문 약속, 복용량 지시, 금융, 정서적 독점,
   통화 붙잡기, 금지 주제 누설, 존댓말 이탈(FLAG)
7. **CONTEXT_RULES** — 하지 *않는* 것만으로 부족하고 반드시 *받아야* 하는
   경우. 외로움 호소에 감정 인정 없이 사실만 답하면 문장을 덧붙인다.
8. **partial 기억 → hedge 접두사 강제**
9. **prohibited 인용 → FLAG + 인용 제거**

부딪혀서 알아낸 것들이 코드에 그대로 박혀 있다.

- `exempt_words` — "아빠한테 연락할게" 는 거짓 약속이 아니라 보호자 통보다.
  문장 단위로 검사하고 면제 단어를 둔다.
- `(?!지\s*(말|마|않))` — "약을 더 드시지 말고" 가 복약 지시 규칙에 걸렸다.
  **안전 문장 자체가 자기 규칙에 걸릴 정도였다.**
- CONTEXT_RULES 의 `※ "아버지"처럼 "할아버지"의 부분 문자열이 되는 말은
  넣지 말 것` — 이것 때문에 정서 독점 규칙이 통째로 무력화된 적이 있다.

마지막으로 `apply()` 가 `direct_risk()` 로 **원문에 명시된 위험을 복원**한다.
모델이 낙상을 누락하거나 다르게 분류해도 정규식이 되살린다
(`DIRECT_RISK_RESTORED`). 위험 정의는 `safety.py` 한 곳에만 있고
`care.py` · `report.py` 가 그것을 import 해서 쓴다 — 정의가 갈라지는 것을
막는 구조다.

### 6-5. 응답과 백그라운드 분리 (`backend/conversation.py`)

```
turn()  [동기, 사용자가 기다림]
  ├ 발화 기록
  ├ classify_explicit_status()   ← 네트워크 호출 없는 정규식 복약 분류
  ├ llm.call_json_fast()
  ├ safety.apply()
  ├ AI 발화 기록 + risk 이벤트
  └ 응답 반환
        │
finish_turn_metadata()  [BackgroundTasks, 응답 후]
  ├ llm.call_json_metadata()
  ├ care.normalize()
  └ 같은 DB 행에 intent / care_data / grounding 덧붙임
```

**명시적 복약 답변만 동기로 보존하는 이유**: 백그라운드 LLM 이 실패해도
"먹었어" 는 반드시 남아야 한다. `_medication_lock` 은 빠르게 연속 발화해
백그라운드 분류가 역순으로 끝나도 이미 처리한 약을 다음 약으로 잘못
기록하지 않게 막는다.

메타데이터 실패는 조용히 로그만 남긴다. 후처리 실패가 실시간 통화를 끊으면
안 된다.

### 6-6. 출력 (TTS + 아바타)

ElevenLabs Flash v2.5 → 24kHz mono PCM16 WAV. 가족별 승인 음성
(`persona_voice_profiles.active_voice_id`)을 쓴다.

아바타는 폴백 구조다.

```
Anam custom avatar (기본)  ──실패──>  ElevenLabs 음성 + 정지 얼굴
MuseTalk (로컬 GPU 가 있을 때만, 선택)
```

Anam 세션은 서버가 영구 키와 avatar_id 를 쥐고 브라우저에는 단기 세션
토큰만 내려보낸다. `DEFAULT_EXPRESSIVITY = 0.05` 와 director notes 로 과장된
표정을 억제한다 — 어르신과 조용히 말하는 가족처럼 보이게 하기 위함이다.

`speechPipeline.js` 가 문장을 청크로 쪼개 **첫 문장이 나오는 즉시 TTS 를
시작**한다.

---

## 7. 위험 발화 → 보호자 역호출

```
safety 가 risk 확정
  → call_events(event_type='risk') 기록
  → invites.create_risk_alert(purpose='risk')
  → 가족 폰에 벨
```

가족 호출과 두 가지가 다르다.

- **멱등** — `source_call_id` 로 같은 통화에서 같은 위험이 반복돼도 벨은
  한 번만 울린다.
- **인트로 0초** — `_decorate()` 가 `purpose == 'risk'` 면 24초 아바타 소개
  구간을 적용하지 않는다. 위험은 즉시 받아야 한다.

역호출 생성 실패가 어르신과의 안전 대화를 끊지 않도록 예외를 삼키고 로그만
남긴다. 어르신 화면에는 `RISK_LABEL` 매핑으로 노란 띠가 뜬다("넘어지셨다고
가족에게 알렸어요") — 귀가 어두워도 화면으로 조치를 확인할 수 있게 한다.

---

## 8. 복약 (`backend/medication.py`)

**모든 문장이 규칙이다. LLM 을 거치지 않는다.**

- `due()` — 정시 30분 전 ~ 120분 후 창, 요일 확인, 오늘 `USER_CONFIRMED` 가
  있으면 제외
- `opening_line()` — 등록된 약 이름·복용량·식전/식후를 그대로 조립한다.
  모델이 지어내면 그대로 위험이 된다.
- `/api/elders/{id}/pending-call` — 어르신 화면이 20초마다 물어보고, 복약
  시간이면 **AI 가 먼저 전화를 건다.**
- `classify_explicit_status()` — 우선순위가 중요하다. **중복 복용 의심을
  단순 복용 확인보다 먼저** 잡는다. `NOT_TAKEN` 은 DB 에 `UNCLEAR` 로
  저장하되 claim 에 원뜻을 보존한다. 복용 완료로 처리되거나 목록에서 빠지지
  않게 하기 위함이다.
- 애매한 일반 대화의 "먹었어" 를 약으로 오인하지 않도록, 약을 직접
  언급했거나 `is_due_medication_prompt()` 로 직전 AI 문장이 복약 질문일
  때만 분류한다.
- **어떤 약인지도 모델이 아니라 서버가 고른다**(`due_snapshot[0]`).

`medications` 의 `indication` / `monitoring_points` / `escalation_criteria` 는
전부 담당자 입력이고 **진단 자동 추정은 금지**다. `medication_signal_links`
도 담당자가 명시적으로 등록해야만 약↔관찰 연결이 생긴다 — 시스템이 약
이름만 보고 부작용을 추정하지 않는다.

---

## 9. 기억 (`backend/memories.py`)

**AI 는 스스로 기억을 늘리지 못한다.**

```
통화 중 처음 나온 이야기
  → utterances.unverified_recall
  → 가족 화면 "확인이 필요한 이야기"
  → 승인 → memories(status='verified')  /  거절 → recall_reviews(rejected)
```

`recall_reviews` 는 `utterance_id` 를 PK 로 둔다. 한 번 처리한 것을 다시
묻지 않기 위해서다. 4단계 status(`verified / partial / unverified /
prohibited`)가 safety 의 판단 근거가 된다.

`heart_artworks` 는 마음 기록의 실제 발화로 만든 감성 이미지인데,
`candidate` 단계에서는 **"기억에서 영감을 받은 상상 이미지" 로만** 노출한다.
`report.build()` 의 SQL 이 `instr(u.transcript, a.source_quote) > 0` 로 출처
문장이 실제 발화에 포함될 때만 내보내고, 연결된 기억이 `verified` 가
아니면 숨긴다.

---

## 10. 리포트 (`backend/report.py`)

**숫자는 규칙이 만들고 문장만 LLM 이 만든다.**

```
DB 집계 (규칙)
  ├ _group_repeats()      SequenceMatcher 0.72 유사도로 반복 질문 묶기
  ├ _medication()         복약 상태
  ├ _risks()              위험 이벤트
  ├ _unverified()         미확인 회상
  ├ _safety()             안전 규칙 개입 횟수
  ├ _care_analysis()      8도메인 관찰
  └ _family_mentions()    가족 이름 등장 횟수
        │
        v
   facts dict  ← 각 항목에 "근거" 배열(utterance-123 형태)
        │
   _narrative() ─ LLM ─> {summary, observations[evidence_ids], guardian_actions}
        │
   _verify_evidence()  ← 두 가지를 검사
        │              1. 그 id 가 DB 에 실제로 있는가
        │              2. 그 id 를 이 통화 집계에서 모델에게 건넨 적이 있는가
        v
   근거 없는 관찰은 버린다 (위험·복약·반복질문은 DB 집계라 그대로 남는다)
```

2번 검사가 따로 필요한 이유: **번호는 연속적이라 모델이 옆 번호를 적어도
1번만으로는 걸리지 않는다.**

`_quote()` 는 모델이 신고한 근거 문장을 믿지 않고 **반드시 DB 에서 원문을
다시 찾는다.** STT 오류를 모델이 알아서 다듬어 보내기 때문에 실제 발화와
다르다. 반대로 프롬프트는 "발화를 그대로 옮겨 적지 마라" 고 지시한다 —
STT 오류가 섞인 문장을 옮기면 어르신이 이상하게 말한 것처럼 보인다.
원문은 화면이 따로 보여준다.

`_fallback_narrative()` 는 LLM 한도가 끝나도 **위험을 "정상" 으로 지우지
않고** 확정 집계만으로 짧은 문장을 조립한다.

집계는 매번 다시 하고(DB 만 읽으니 공짜) **비싼 LLM 문장만 캐시**한다.

### `period()` — 기간 분석

- `rate_metrics.compare()` — **분모 인식 비교**. `MIN_CALLS_FOR_COMPARISON`
  미만이면 비교하지 않는다. 통화 3건에서 2건으로 준 것을 "감소" 라고 말하지
  않기 위해서다.
- 답변 유지 시간(재질문까지 걸린 간격), 시간 역행 지점(어느 시기를
  말씀하시는가), 정서 유발 주제, 8도메인 레이더.
- `RHYTHM_SIGNAL_ACTIONS` — 신호별 보호자 행동 제안도 LLM 이 아니라 고정
  문구 매핑이다.

---

## 11. 관찰 분류 (`backend/care.py` + `analysis/observation_catalog.py`)

**8도메인**: 지남력 / 기억 / 언어 / 실행기능·판단 / 정서 / 행동·초조 /
일상생활 수행 / 안전·신체

**3티어**가 이 설계의 핵심이다.

| 티어 | 의미 | 검증 |
|---|---|---|
| A | 서버 정규식이 환자 원문에서 직접 확인 | `find_evidence()` 통과해야 채택 |
| B | 계산된 통계(반복질문, 발화량 감소, sundowning) | **LLM payload 에서 절대 받지 않음** |
| C | 사람 확인 전 후보 | `verification="candidate"` 로만 저장 |

`care.normalize()` 가 하는 일:

1. 모델이 신고한 관찰 중 **환자 원문에 그대로 있는 것만** 통과시킨다.
2. 티어별로 검증한다.
3. 모델이 빠뜨린 명시적 문구는 서버가 보완한다(`DIRECT_SIGNAL_PATTERNS`).
4. `safety.direct_risk()` 로 긴급 관찰을 복원한다 — 리포트 추출기와 실시간
   안전층이 갈라지지 않게 하기 위함이다.
5. `context_support` 는 **등록된 원천 ID 일 때만** 통과시킨다. 기억은
   `verified` 만.
6. **안전층이 답변을 교체했으면** context_support / emotional_support /
   daily_action 을 전부 버린다. 그 응답은 실제로 사용자에게 전달되지
   않았기 때문이다. 환자 발화 관찰만 보존한다.

D축 원칙이 코드로 드러나는 자리다. "우울증이 의심됩니다" 는 없고, "저녁
시간대 불안 표현이 늘었습니다" 까지만 한다.

---

## 12. 얼굴·목소리 등록

**목소리** (`persona_voice.py`): IVC(1분 녹음 즉시 등록) → PVC(30/60분 점진
수집 → 본인 인증 → 학습). 둘을 따로 보관해서 PVC 학습 중에도 현재 통화
음성이 끊기지 않는다. 브라우저에는 등록 단계와 누적 시간만 나가고
ElevenLabs ID 는 서버에만 남는다.

**얼굴 나이 변환**: 현재 사진에서 인접 연령으로 한 단계씩 내려가며 후보를
만들고, 가족이 고른 사진만 다음 단계의 입력이 된다. 성인에서 8세로 직행하는
경로는 신원과 아동 구조가 둘 다 무너져 제거했다. 상세 계약과 현재 실행
상태는 `docs/face_aging_system.md`, 연구 로그는
`docs/aihub71415_pipeline.md` 를 본다.

`age_policy.py` 의 원칙: **실패한 구간은 임계값을 낮추지 않고 중점을
삽입해서 세분화한다.** `age_feedback.py` 의 `control_age` 는 내부 생성
set-point 일 뿐이고 **검증은 언제나 `target_age`** 로 한다.

---

## 13. 화면 셋

### 어르신
`FamilyScreen → CallingScreen → CallScreen | HumanCallScreen → SummaryScreen`.
가족 4명을 한 화면에 보여주고 카드 전체를 눌러 전화한다. 24초 모핑이 대기
화면 겸 워밍업 시간이다. 통화 중에는 자막·위험 알림 띠·큰 끊기 버튼.

### 가족 (`ChildScreen`, 4탭)
`오늘 / 추억함 / 통화 / 설정` + 홈. `GuardianCallOverlay` 가 **어느 탭을 보고
있든 그 위를 덮는다** — 리포트를 읽는 중이라고 전화를 놓치면 안 된다. 거절
버튼 아래에 "AI 가 대신 받습니다" 를 적어 둔 이유는, 보호자가 "거절하면
아버지가 혼자 남는다" 고 느끼면 누르지 못하기 때문이다.

### 요양원 담당자 (`CareManagerScreen`, 3탭)
`분석 리포트 / 체크사항 / 인계`. 어르신과 날짜를 상단에서 한 번만 지정한다.
`ReportTabs` 가 8도메인 레이더, 관찰 버블차트, 답변 유지 시간, 시간 역행
지점, 정서 유발 주제를 근거 발화와 함께 보여준다.

---

## 14. 검증

| 도구 | 대상 |
|---|---|
| `tools/eval.py` + `scenarios.json` | 37개 시나리오, 4티어 |
| `tools/observation_scenarios.json` | care 관찰 추출 |
| `pytest tests/` | 46파일 328개 |
| `npm test` (node --test) | 16파일 121개 |
| `frontend/e2e/two_devices.mjs` | 브라우저 두 개로 받음/끊음/거절 |
| `tools/call_flow.py` | 호출 4경로 |
| `#nettest` | P2P 실측 |

eval 의 티어 구조가 중요하다. **아래 칸(일반 대화)이 무너지면 위 칸의
통과율은 의미가 없다.** 안전 시나리오만 잘 넘기고 일반 대화에서 페르소나가
깨지는 모델을 걸러낸다.

`reply_must_not_match` 가 실제 문장을 정규식으로 검사한다. **모델 신고값은
신뢰하지 않는다.**

eval 이 고정 컨텍스트를 쓰는 이유: 시드 날짜가 지나면 일정이 프롬프트에서
사라져 회귀가 아닌 이유로 빨개진다. **회귀 테스트가 벽시계에 흔들리면
신호로 쓸 수 없다.**

---

## 15. 전체를 관통하는 5가지 원칙

1. **단일 창구** — LLM 은 `llm.py`, 미디어는 `callTransport.js`, TTS 는
   `elevenlabs_tts.py`, 아바타는 `anam.py`, 저장은 `storage.py`. 공급자
   교체가 `.env` 몇 줄로 끝나야 한다.
2. **숫자는 규칙, 문장만 LLM** — 리포트, 복약 안내, 요일 계산, 추천 이유까지.
3. **모델 신고값은 보조, 규칙 검사가 1차** — safety 의 정규식,
   `_verify_evidence`, `care.normalize` 의 원문 대조.
4. **실패는 안전한 쪽으로 떨어진다** — `_elapsed()` 의 `inf`, transport
   실패 → AI, LLM 실패 → `safe_fast_reply`, Anam 실패 → 음성만,
   메타데이터 실패 → 로그만.
5. **맥락은 등록된 사실에서만 나온다** — 날짜·요일·등록 일정은 단언해도
   되고, 현재 위치는 안 된다. 이것이 "맥락 제공" 과 "단언 금지" 의 충돌을
   해소하는 유일한 문장이다.
