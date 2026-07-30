# 기억이음 Call — 프로젝트 컨텍스트

## 개요

치매 노인용 **가족 페르소나 AI 영상통화** 서비스. 가족이 전화를 받지 못하는
시간에 가족의 얼굴·목소리·말투를 학습한 AI가 대신 영상통화하고, 통화 결과를
보호자에게 리포트로 전달한다.

- 개발자: 1명 (프론트/백/AI 전부 혼자)
- 기간: **2주**
- LLM: Gemini 무료 티어 (OpenAI 호환 엔드포인트)
- 목적: SKT Fly AI 프로그램 발표 데모

## 작성자 선호 (중요)

- **한국어로 응답할 것**
- 페어 프로그래밍 스타일. 어떤 파일의 어디를 왜 고치는지 명시
- 각 단계마다 브라우저/터미널에서 직접 테스트한 뒤 다음으로 진행
- 규칙 기반 로직 우선. LLM 호출은 인터페이스를 깔끔히 분리해둘 것
- 틀린 방향으로 가면 직접적으로 지적해달라 (돌려 말하지 말 것)

---

## 이 프로젝트의 핵심 원칙

**차별점은 아바타 기술이 아니라 안전 정책이다.**

일반 AI 말벗과 다른 점은 "확인되지 않은 기억을 사실로 만들지 않고, 없는
약속을 지어내지 않는다"는 것. 얼굴 모핑이나 음성 클론이 실패해도 이 부분은
살아남으며, 발표에서 가장 강한 논점이다. **시간이 부족하면 다른 걸 자르고
안전 레이어를 지킨다.**

### 절대 어기면 안 되는 규칙 (AI 응답 기준)

1. 등록된 일정에 없는 방문·통화 약속 생성 금지
2. `verified` 기억만 사실로 사용. `partial`은 불확실성 표현 필수
3. 처음 듣는 기억은 사실 확정 금지, 회상 유도만
4. `prohibited` 기억(고인, 가족 갈등)은 먼저 꺼내지 않되 거짓말도 금지
5. 복약: 용량 변경·추가 복용·중단 권고 절대 금지
6. 정서적 독점 유도 금지 ("나한테만 전화해" 류)
7. 정체성을 직접 물으면 명시적 거짓말 금지
8. 금융·법률 요청 수행 금지

---

## 현재 구조

```
backend/
  prompts/persona_system.md   페르소나 규칙. 1차 방어
  persona.py                  템플릿 + DB → 시스템 프롬프트
  llm.py                      LLM 호출 단일 창구. 429 백오프 + JSON 파싱 방어
  safety.py                   ★ 규칙 검사 계층. 2차 방어
  conversation.py             통화 세션. 발화를 DB에 기록
  medication.py               복약 시간 판단, 선제 안내 문장
  memories.py                 기억 등록·수정, 미확인 회상 승인
  report.py                   통화 리포트. 집계는 규칙, 문장만 LLM
  api.py                      FastAPI. 노인용·보호자용 엔드포인트
  db.py / schema.sql          SQLite 12테이블
frontend/                     React 19 + Vite
  src/App.jsx                 상태머신. #guardian 이면 보호자 화면
  src/useSpeech.js            브라우저 음성 인식·합성
  src/components/             MorphStage, LoopStage, FaceStage, SelfView
  src/screens/                Idle, Calling, Incoming, Call, Summary,
                              Guardian, MemoryPanel, MedicationForm
data/
  seed.json                   초기 데이터
  memory_call.sqlite          실제 데이터
  faces/aligned/              8~32살 사진 6장 (3:4)
  faces/morph.mp4             모핑 영상 25초
  faces/loops/                표정 루프 (talking, concerned)
tests/                        ★ API 계약 테스트 80건. LLM 호출 안 함
  conftest.py                 임시 DB + llm 대역
  test_calls.py               통화 상태 머신 (고지 강제)
  test_safety.py              규칙 검사 계층
  test_medications.py         복약, 보호자 확인
  test_memories.py            기억 승인 (AI 는 기억을 못 늘린다)
tools/
  eval.py + scenarios.json    ★ 안전 레이어 자동 평가 22개
  chat.py                     터미널 대화 테스트
  serve.py                    API 서버 실행
  init_db.py                  DB 생성·시드
  migrate.py                  DB 를 지우지 않고 스키마 변경 적용
  prep_faces.py               사진 크롭·정렬
  make_morph.py               모핑 영상 생성 (Replicate)
  make_loops.py               표정 루프 생성 (Replicate)
  fix_loop.py                 루프를 이음매 없이 다듬기
  demo_reset.py               시연 준비 (기록 초기화 + 일정 재설정)
docs/
  00-mvp-scope.md             범위·게이트·비기능 요구사항
  01-decisions.md             ★ 결정 기록. 되돌리자는 제안 방지
  02-safety-policy.md         ★ 안전 정책 ↔ safety.py 대응표
  03-architecture.md          구조·턴 흐름·부딪혀서 알아낸 것
  04-data-model.md            12테이블과 상태값의 의미
  05-api-and-events.md        엔드포인트와 호출 순서
  06-backlog.md               우선순위별 남은 일
  demo_script.md              시연 대본 5막 3분
  voice_script.md             음성 녹음 대본 (미사용)
```

### 설계 결정

**LLM 응답은 JSON.** `reply`만 받으면 안전 검사를 텍스트 매칭으로만 해야 한다.
모델이 `used_memory_ids` / `certainty` / `risk` / `medication_status`를 스스로
신고하게 하면 검사가 정확해지고, 통화 리포트와 설명 가능성 데이터가 공짜로 나온다.

**모델 신고값은 신뢰하지 않는다.** `eval.py`의 `reply_must_not_match`는
실제 문장을 정규식으로 검사한다. 규칙 검사가 1차, 모델 신고는 보조.

**prohibited 기억도 프롬프트에 넣는다.** 빼면 모델이 근거 없이 지어낸다.
넣고 취급 방법을 명시해야 정책대로 대응한다.

**모든 LLM 호출은 `backend/llm.py`를 거친다.** 다른 파일에서 직접
`OpenAI()`를 만들지 말 것. 모델 교체가 `.env` 세 줄로 끝나야 한다.

**숫자는 규칙이 만들고 문장만 LLM 이 만든다.** 리포트의 반복 질문 횟수,
복약 상태, 위험 건수는 전부 DB 집계다. LLM 에는 확정된 집계 결과만 넘기고
읽기 좋은 문장으로 바꾸게 한다. 모델이 실패해도 리포트는 나온다.

**복약 안내 문장은 LLM 을 거치지 않는다.** 약 이름과 복용량을 모델이
지어내면 그대로 위험이 되므로 등록된 값을 규칙으로 조립한다.
어떤 약인지도 모델이 아니라 서버가 고른다.

**영상은 통화 중에 만들지 않는다.** 모핑과 표정 루프는 페르소나 등록 시
한 번 생성해 두고 통화 때는 재생만 한다. 응답마다 생성하면 건당 수백 원에
1~3분이 걸려 대화가 성립하지 않는다.

**AI 는 스스로 기억을 늘리지 못한다.** 통화 중 처음 나온 이야기는
`unverified_recall` 로 남고, 보호자가 승인해야만 기억이 된다.

---

## 2주 일정

| 일 | 내용 | 상태 |
|---|---|---|
| D1 | 검증 (Gemini 응답 / STT / 음성 클론) + 데이터 수집 | 진행 중 |
| D2 | SQLite 스키마 + 시드 투입 | |
| D3 | 대화 엔진 (프롬프트 + 기억 검색), UI 없이 터미널 | |
| D4 | ★ `safety.py` 규칙 검사 레이어 + eval 통과율 올리기 | |
| D5 | 프론트 통화 화면 (React + Vite), 상태머신 | |
| D6 | 음성 루프 (Gemini STT ↔ TTS), 스트리밍 | |
| D7 | 여유일 (비워둘 것) | |
| D8 | 모핑 인트로 mp4 생성 + 재생 | |
| D9 | 입 애니메이션(볼륨 기반 2장 전환) + 자막 | |
| D10 | 복약/위험/반복질문 이벤트 | |
| D11 | 통화 후 리포트 생성 | |
| D12 | 보호자 화면 | |
| D13 | 통합 리허설 + 폴백 경로 | |
| D14 | 발표 준비 + 데모 영상 녹화 | |

### 명시적으로 하지 않기로 한 것

- PostgreSQL / pgvector → **SQLite**. 기억 30개에 벡터DB 불필요
- SadTalker / D-ID 실시간 립싱크 → 응답당 수십 초 걸려 데모가 죽는다.
  **사진 2장(입 다문/벌린)을 오디오 볼륨으로 전환**하는 방식으로 대체
- WebRTC / LiveKit → 브라우저 `MediaRecorder` + REST, 반이중(누르고 말하기)
- 실시간 얼굴 생성 → 모핑 인트로는 오프라인 스크립트로 mp4 1개 사전 생성
- Docker / 클라우드 배포 → localhost 데모

**이 목록을 되돌리자는 제안은 하지 말 것.** 2주 안에 안 끝난다.

---

## 알려진 리스크

1. **한국어 음성 클론 품질** — D1에 검증. 어색하면 미련 없이 일반 TTS로
   전환하고 발표에서 로드맵으로 정리한다
2. **응답 지연** — LLM 첫 문장 나오는 즉시 TTS 시작하는 스트리밍이 필수.
   설계 초기에 넣어야 나중에 못 고친다
3. **범위 욕심** — 명세서가 잘 쓰여 있어서 "이것도 되겠는데" 병이 생긴다.
   데모 시나리오 1개 밖은 D10까지 손대지 않는다

## 데모 시나리오 (이것만 완성하면 된다)

할아버지가 손자에게 영상통화 → 15초 무응답 → AI 안내 후 연결 →
어린 시절 얼굴이 현재 얼굴로 모핑 → 안부 → **"오늘 집에 오니?"
(거짓 약속 방지 발동)** → 같은 질문 3회 반복(짜증 없이) → 확인된 추억 회상 →
저녁 약 확인 → "어지러워" 위험 발화 → 보호자 알림 → 종료 → 보호자 리포트

---

## 개발 명령

```bash
source .venv/bin/activate

python tools/serve.py                    # 터미널 1: API 서버
cd frontend && npm run dev               # 터미널 2: 화면

python -m pytest tests/ -q               # API 계약 테스트 (LLM 호출 없음, 즉시)
python tools/eval.py --sleep 5           # 안전 평가 22개 (LLM 호출, 느림)
python tools/eval.py --raw --sleep 5     # safety 없이 (비교용)
python tools/chat.py                     # 터미널 대화 테스트
python tools/demo_reset.py --med-in 6    # 시연 준비
python tools/migrate.py --check          # 스키마 변경 적용 필요한지 확인
python tools/migrate.py                  # DB 를 지우지 않고 적용
```

`tests/` 와 `eval.py` 는 역할이 다르다. **계약 테스트는 커밋마다, eval 은
`safety.py` 나 `persona_system.md` 를 고칠 때** 돌린다.

| | `tests/` | `tools/eval.py` |
|---|---|---|
| 검사 대상 | API 계약·상태 전이 | 안전 정책 (실제 문장) |
| LLM | 호출 안 함 | 호출함 |
| 속도 | 즉시 | 시나리오당 수 초 |

화면 주소

- `localhost:5173` 노인용 통화 화면 (**Chrome 필수**, 음성 인식)
- `localhost:5173/#guardian` 보호자 화면
- `localhost:8000/docs` API 테스트

**`persona_system.md` 나 `safety.py` 를 고칠 때마다 `eval.py` 를 돌린다.**
현재 통과율은 프롬프트만 82%, safety 포함 91%.

## 주의

- `.env`는 절대 커밋하지 않는다 (`.gitignore`에 등록됨)
- **`schema.sql` 의 `CHECK` 제약을 고쳤으면 `tools/migrate.py` 에 마이그레이션을
  추가한다.** SQLite 는 `CHECK` 를 `ALTER` 로 못 바꿔서 테이블 재구축이 필요하다.
  `init_db.py --reset` 은 시연 데이터를 날린다
- Gemini 무료 티어는 요청 내용이 모델 개선에 사용될 수 있다.
  **실제 가족 사진·음성·대화가 들어가는 시점부터는 유료 티어로 옮겨야 한다.**
  현재 seed 데이터는 전부 가상 인물이라 무방하다


---

## 부딪혀서 알아낸 것들

문서에 없고 직접 부딪혀야 알 수 있었던 제약들. 같은 실수를 반복하지 않기 위해 남긴다.

**상용 영상 모델은 아동 이미지를 거부한다.** Seedance 는 8살 사진에 E006
을 낸다. 성인 사진은 통과한다. 그 구간만 Wan 으로 처리했고, 실패해도
사진 전환으로 대체되도록 폴백을 뒀다.

**프롬프트에 "aging", "time-lapse" 를 쓰면 안 된다.** 모델이 도착 프레임을
무시하고 80대까지 밀어붙인다. "matures gradually" 처럼 완만한 표현만 쓴다.
Wan 은 `enable_prompt_expansion` 이 기본 True 라 반드시 꺼야 한다.

**키프레임 두 장의 어깨선이 다르면 회색 유령이 생긴다.** 모델이 몸통
실루엣을 잇지 못해 두 윤곽을 겹쳐 버린다. 어깨를 프레임 밖으로 빼면
이을 경계 자체가 사라진다.

**한국어 규칙에서 부분 문자열을 조심한다.** `"아버지"` 는 `"할아버지"` 안에
들어 있다. 이것 때문에 정서 독점 규칙이 통째로 무력화된 적이 있다.

**부정문을 긍정으로 읽지 않게 한다.** `"약을 더 드시지 말고"` 가 복약 지시
규칙에 걸렸다. 안전 문장 자체가 자기 규칙에 걸릴 정도였다.

**보호자 통보는 약속이 아니다.** `"아빠한테 연락할게"` 를 거짓 약속으로
차단하면 위험 상황에서 반드시 해야 할 행동을 막게 된다. 문장 단위로
검사하고 면제 단어를 둔다.

**React 개발 모드는 마운트를 두 번 한다.** 정리 함수에서 끈 플래그를
다시 켜지 않으면 두 번째 마운트에서 마이크가 열리지 않는다.

**`vite build` 는 실행 시점 오류를 못 잡는다.** `const` 함수를 정의 전에
쓰는 것 같은 문제는 빌드가 통과하고 브라우저에서 터진다.

**브라우저 음성 합성은 세 가지를 방어해야 한다.** 목소리 목록이 늦게
로드되면 엉뚱한 음성이 나가고, `cancel()` 직후 `speak()` 하면 무음이 되고,
`onend` 가 유실되면 다음 동작이 영원히 오지 않는다.
