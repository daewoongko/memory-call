# 다소니 (memory-call)

치매 어르신이 잃기 쉬운 현재의 맥락을 가족의 얼굴·목소리·확인된 추억으로
연결하고, 보호자가 실제 통화 근거를 확인할 수 있게 만든 영상통화형 돌봄
프로토타입입니다.

치료·예방·진단이나 기억 회복을 주장하지 않습니다. 등록되지 않은 일정과
확인되지 않은 기억을 사실처럼 말하지 않는 것이 제품의 가장 중요한 원칙입니다.

배포: <https://memory-call.onrender.com>

## 현재 데모 기준

| 항목 | 값 |
|---|---|
| 대표 날짜 | 2026-08-31 |
| 통화 데이터 | 40통, 총 160분 |
| 확인된 기억 | `mem_016` — 대웅이와 강가 공놀이 |
| 얼굴 타임라인 | 8·9·10·11·12·15·17·20·24·28세 |
| 연결 인트로 | 24.2초, 30fps |
| 대기 음원 | 자연 배경음과 연결 안내가 포함된 24.2초 음원 |
| TTS | ElevenLabs, 승인 재생 속도 0.93 |
| 말하는 얼굴 | Anam, 실패하면 음성 통화로 안전하게 폴백 |

데모 진행 순서와 사용할 발화는 [데모 실행 가이드](docs/demo_runbook.md)에 따로
정리했습니다. 위 값의 코드 기준점은 `tools/demo_config.py`입니다.

## 핵심 흐름

```text
어르신이 가족에게 전화
        │
        ├─ 24.2초: 자연 음원 + 8→28세 얼굴 모핑
        │
        ├─ 보호자가 받음 ────────────> WebRTC 사람 통화
        │
        └─ 거절·무응답·연결 실패 ───> 가족이 준비한 AI 기억통화
                                           │
                           STT → LLM → 안전 규칙 → TTS/Anam
                                           │
                              발화·근거·관찰을 SQLite에 기록
                                           │
                                  보호자 리포트와 그림일기
```

보호자가 일찍 받아도 인트로가 끝난 뒤 사람 화면으로 전환합니다. 화면이 꺼져
가족 기기를 깨울 수 없거나 WebRTC가 실패하면 어르신을 오류 화면에 남기지 않고
AI 통화로 이어갑니다.

## 안전 계약

- `verified`이고 `conversation_allowed=true`인 기억만 사실로 사용합니다.
- 처음 나온 이야기는 `unverified`로 저장하고, 보호자가 확인하기 전에는 통화
  기억으로 재사용하지 않습니다.
- 등록되지 않은 방문·전화 약속, 현재 위치, 식사·복약 상태를 추측하지 않습니다.
- 복약 변경, 금융·법률 행동, 정서적 독점 유도는 차단합니다.
- 정체성을 직접 물으면 가족 본인이라고 속이지 않고 “가족이 준비한 기억통화”라고
  설명합니다.
- 위험 발화는 한 가지 확인 질문 뒤 보호자 확인이 필요하다는 기록을 남깁니다.
- 리포트는 진단이 아니라 실제 발화에 근거한 관찰만 보여줍니다.

세부 관찰 설계는 [analysis_design.md](docs/analysis_design.md), 얼굴 생성·검증
계약은 [face_aging.md](docs/face_aging.md)를 참고하세요.

## 저장소 구조

```text
backend/
  api.py                 FastAPI 진입점과 HTTP/WebSocket API
  conversation.py        통화 한 턴의 기록·응답 흐름
  persona.py             가족 설정과 확인된 기억으로 프롬프트 구성
  safety.py              규칙 기반 최종 안전 검증
  report.py              통화 근거 기반 보호자 리포트 집계
  invites.py             수신·거절·무응답·AI 인계 상태 머신
  elevenlabs_*.py        실시간 STT와 TTS
  anam.py                 말하는 얼굴 세션
  storage.py             로컬/배포 저장 경로
  schema.sql              SQLite 스키마

frontend/src/
  App.jsx                 역할과 통화 상태를 연결하는 앱 루트
  screens/                어르신·보호자·온보딩 화면
  useSpeech.js            STT/TTS 수명주기
  callTransport.js        WebRTC 전송 경계
  waitingMelody.js        연결 대기 음원

data/
  seed.json               고길동 가족·확인 기억 기준 데이터
  gildong_diaries_2026.json  92일 그림일기와 대표 시연일
  faces/                  승인된 대웅 얼굴 후보·키프레임·최종 모핑
  voice/reference.wav     공개 승인된 데모 음성 기준 파일

tools/
  demo_config.py          발표 데이터 단일 기준
  seed_gildong_demo.py    발표용 SQLite 생성
  demo_reset.py           현재 DB를 발표 상태로 원자적 교체
  start.py                배포 시작점
  serve.py                로컬 API 개발 서버
  face_aging/             연구·생성 도구

tests/                    Python 계약·통합 테스트
frontend/test/            Node 기반 프론트 정적·동작 테스트
```

`data/personas/`는 런타임에 사용자가 등록한 개인 자산이 저장되는 위치이며 Git에
올리지 않습니다. 최종 데모 자산은 중복 없이 `data/faces/`만 사용합니다.

## 로컬 실행

### 요구 사항

- Python 3.12
- Node.js 22
- 선택: Docker

### 1. 환경 변수

```powershell
Copy-Item .env.example .env
```

macOS/Linux에서는 `cp .env.example .env`를 사용합니다. 최소한 다음 공급자를 실제로
시험할 때만 키를 채웁니다.

- `OPENAI_API_KEY`: 대화 모델
- `ELEVENLABS_API_KEY`: 실시간 STT와 가족 음성 TTS
- `ANAM_API_KEY`: 말하는 얼굴

키가 없어도 많은 화면과 테스트는 실행할 수 있지만 해당 외부 기능은 사용할 수
없습니다. `.env`, SQLite, 비공개 녹음은 Git에 포함되지 않습니다.

### 2. 백엔드

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\init_db.py
.\.venv\Scripts\python.exe tools\serve.py
```

API는 <http://127.0.0.1:8000>, Swagger 문서는 <http://127.0.0.1:8000/docs>에서
확인합니다.

### 3. 프론트엔드

다른 터미널에서 실행합니다.

```powershell
Set-Location frontend
npm ci
npm run dev
```

브라우저에서 <http://127.0.0.1:5173>을 엽니다. Vite가 `/api`, `/media`,
`/age-candidates` 요청을 로컬 FastAPI로 전달합니다.

### 발표 데이터로 초기화

```powershell
.\.venv\Scripts\python.exe tools\demo_reset.py
```

기존 DB가 있으면 가족별 음성·아바타 설정을 보존한 채 임시 DB를 만든 후 원자적으로
교체합니다. 결과는 2026-08-31, 40통, 160분, 92일 그림일기 기준입니다.

## 테스트

```powershell
# 백엔드 전체
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 프론트 전체와 프로덕션 빌드
Set-Location frontend
npm test
npm run build
```

배포 이미지까지 확인하려면 저장소 루트에서 실행합니다.

```powershell
docker build -t memory-call:local .
docker run --rm -p 8000:8000 --env-file .env memory-call:local
```

외부 API 키가 필요한 실시간 품질 검사는 단위 테스트와 별도로 실제 기기에서
확인합니다. 최소 점검 항목은 다음과 같습니다.

1. 모바일에서 연결 음원과 모핑이 정확히 24.2초 재생되는가
2. 보호자가 받으면 인트로 뒤 사람 통화로 전환되는가
3. 무응답이면 AI 통화가 시작되고 TTS가 0.93 속도로 들리는가
4. Anam이 실패해도 음성 대화가 이어지는가
5. 미확인 이야기가 “함께 보는 추억”에 바로 노출되지 않는가
6. 리포트 수치와 근거 발화가 같은 통화 데이터에서 계산되는가

## 배포

`main`에 푸시하면 GitHub Actions가 Python 테스트와 Docker 빌드를 수행합니다.
`render.yaml`은 CI가 통과한 커밋만 Render에 자동 배포하도록 설정되어 있습니다.

배포 환경에서 필요한 비밀 값은 Render 대시보드에만 저장합니다.

- `OPENAI_API_KEY` 또는 `LLM_API_KEY`
- `ELEVENLABS_API_KEY`
- `ANAM_API_KEY`
- TURN 설정(외부망 WebRTC를 쓸 때)
- Web Push VAPID 키(고정 키를 쓸 때)

배포 확인:

```powershell
Invoke-RestMethod https://memory-call.onrender.com/api/health
```

서버 시작 시 `DEMO_SEED_MODE=gildong`이면 현재 DB가
`tools/demo_config.py`의 계약과 일치하는지 확인합니다. 날짜·통화 수·총 시간·대표
기억이 다르면 발표 DB를 다시 만들기 때문에 이전 설정이 남아 데모 수치가
어긋나는 일을 막습니다.

## 자산과 개인정보

- 공개 승인된 최종 데모 얼굴·음성만 재현 가능한 일반 Git 객체로 추적합니다.
- 생성 중간 파일, QC 캡처, 후보 영상, 런타임 업로드는 Git에서 제외합니다.
- 다른 사람의 얼굴·음성을 추가할 때는 목적과 사용 범위에 대한 명시적 동의가
  필요합니다.
- `.env`, 자격 증명, 토큰, 데이터베이스, 원본 개인 녹음은 커밋하지 않습니다.
- 과거 커밋의 대용량 자산까지 완전히 제거하려면 별도의 이력 재작성과 강제 푸시가
  필요합니다. 일반 정리 커밋에서는 이력을 바꾸지 않습니다.

## 구현 범위와 한계

현재 구현에는 역할별 온보딩, 얼굴 후보 선택, 연령 모핑, 가족 음성, 영상통화,
확인 기억, 그림일기, 통화 근거 리포트, 위험 기록이 포함됩니다.

아직 의료기기가 아니며 진단·처방·응급 구조를 대신하지 않습니다. 외부 사용자를
받기 전에는 SMS 본인 확인, 계정 복구, 로그인 시도 제한, 역할 기반 접근 통제,
운영 모니터링과 개인정보 보유·삭제 정책을 추가해야 합니다.

## 관련 문서

- [데모 실행 가이드](docs/demo_runbook.md)
- [관찰 분류와 분석 설계](docs/analysis_design.md)
- [얼굴 연령 변환 계약](docs/face_aging.md)
- [환경 변수 예시](.env.example)
