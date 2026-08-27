# 다소니 (memory-call)

치매 어르신이 잃기 쉬운 현재의 맥락을 가족의 얼굴·목소리·추억으로 연결하고,
가족과 요양 담당자의 반복 설명·안심 부담을 줄이는 인지·정서 케어 서비스입니다.
치료·예방이나 기억 회복을 주장하지 않으며, 확인되지 않은 사실과 감정을 만들어
내지 않는 것을 기본 원칙으로 둡니다.

서비스 범위와 표현 원칙은 [`docs/service_definition.md`](docs/service_definition.md),
관찰·분석 기준은 [`docs/analysis_design.md`](docs/analysis_design.md)를 참고하세요.

> 이 저장소에는 프로젝트 소유자가 공개를 승인한 얼굴·음성 자산과 일부 개인화
> 가중치가 Git LFS로 포함됩니다. 다른 사람의 생체정보를 추가할 때는 명시적
> 동의를 받아야 합니다. API 키, 런타임 DB, 비공개 녹음은 Git에 포함하지 않습니다.

## 현재 제품 구조

일반 실행의 사용자 여정은 `로그인 → 역할 선택 → 역할별 최초 설정 → 메인 화면`입니다.
한 계정으로 여러 역할을 사용할 수 있고, 역할별 현재 단계와 입력값은 SQLite에
즉시 저장되어 앱을 닫아도 이어서 시작합니다. 개발 전용 해시 직행(`#elder`,
`#family`, `#care`)은 Vite 개발 모드에서만 열리며, 배포 앱은 로그인과 최초 설정을
건너뛸 수 없습니다.

현재 로그인은 휴대전화 번호와 숫자 6자리 간편번호를 사용합니다. 간편번호는
PBKDF2 해시로, 세션은 원본 대신 SHA-256 해시로 저장합니다. 다만 휴대전화 소유권을
확인하는 SMS 발송 공급자는 아직 연결되지 않았으므로 `phone_verified_at`을 분리해
두었습니다. 실제 외부 이용자를 받기 전에는 SMS 인증, 로그인 시도 제한, 계정 복구,
전체 환자 API의 역할 기반 접근 통제를 반드시 연결해야 합니다.

| 화면 | 주 사용 목적 |
|---|---|
| 어르신 | 가족에게 전화하거나, 연결되지 않을 때 가족 기반 AI 통화를 이어감 |
| 가족 | 직접 통화, 오늘의 마음 기록·가족 추억함 확인, 얼굴·목소리 설정 |
| 요양원 담당자 | 어르신별 관찰 리포트·정서 주제·복약·일정·인계를 근거와 함께 확인 |

### 역할별 최초 설정

- 어르신: 동의 주체 선택 → 개인정보·민감정보·통화 저장 동의 → 연결 가족 확인 →
  호칭·보기·듣기 설정 → 가족 카드 사용 연습 → 통화 화면
- 가족: 별도 얼굴·목소리 동의 → 어르신 기기의 6자리 번호 확인 → 관계·호칭 →
  본인 사진 등록과 대표 사진 확정 → 말투 카드 → 실제 음성 품질 확인·녹음 → 연결 승인
- 요양 담당자: 기관 코드·직원·직무 확인 → 접근·보안 동의 → 담당 어르신 배정 →
  담당자 화면

동의 이력은 역할, 대상 어르신, 동의 주체 방식, 문서 버전, 동의 시각을 항목별로
저장합니다. 현재 문구 버전은 `2026-08-24.v1`이며 법률 검토 전 UI 초안입니다.
실제 개인정보 처리방침에는 처리업체·국가·항목·목적·보유 기간·거부 시 제한을
운영 설정과 일치하게 확정해야 합니다.

통화는 두 경로로 동작합니다.

- 사람 통화: WebRTC P2P(STUN only)로 음성·영상을 연결합니다. 미디어 연결이
  실패하면 어르신에게 오류를 노출하지 않고 AI 통화로 인계합니다.
- AI 통화: ElevenLabs 실시간 STT → OpenAI 호환 LLM 답변 → 서버 안전 검사 →
  ElevenLabs 가족별 음성 → Anam 가족별 아바타 순서입니다. Anam이 없거나
  실패해도 같은 음성으로 통화가 계속됩니다.

MuseTalk은 로컬 GPU에서만 사용하는 선택적 립싱크 대체 경로입니다. 일반 통화와
배포 앱에는 필요하지 않습니다. 통화 전 권한 확인, 화면 Wake Lock, PWA 설치,
API 비캐시 service worker가 포함되어 있습니다.

벨은 **항상 24초** 동안 울립니다(`backend/invites.py`의 `INTRO_DURATION_SEC`).
어르신 화면에서 같은 24초 동안 재생되는 가족 AI 영상·대기 음악과 정확히 겹쳐야
하기 때문에, 받을 가족 기기가 있든 없든 같은 값을 씁니다. 받을 기기가 없다는
사실(`no_live_device`)은 대기 시간을 줄이는 데 쓰지 않고 무응답 사유를
`timeout`과 `no_device`로 구분하는 데만 씁니다. 가족이 24초 안에 받아도 이
구간을 마친 뒤 사람 통화로 전환합니다. 예외는 위험 발화 역호출로, 이때는
아바타 소개 구간 없이(0초) 곧바로 울립니다.

현재 UI는 모바일 세로 화면을 우선합니다. 어르신 화면은 네 명의 가족을 한 화면에
보여주며 카드 전체를 눌러 전화합니다. 가족 화면은 오늘·추억함·통화·설정의 네
영역으로 나뉘고, 요양 담당자 화면은 선택한 어르신과 날짜를 상단에서 한 번만
지정한 뒤 분석 리포트·체크사항·인계를 확인합니다. 인계 목록은 미완료 업무를
우선 표시하고 완료 업무는 필요한 높이만 사용합니다.

## 로컬 실행

프로젝트 루트에서 Git LFS 자산과 의존성을 준비합니다.

```powershell
git lfs install
git lfs pull
Copy-Item .env.example .env
cd frontend
npm ci
cd ..
```

`.env`에 필요한 공급자 키를 입력한 뒤 터미널 두 개를 사용합니다.

```powershell
# 터미널 1 — FastAPI와 빌드된 프론트(8000)
cd C:\Users\PJ02\Documents\Codex\memory-call
.\.venv\Scripts\python.exe tools\serve.py --no-reload
```

```powershell
# 터미널 2 — Vite 개발 화면(5173)
cd C:\Users\PJ02\Documents\Codex\memory-call\frontend
npm run dev
```

- 개발 화면: http://127.0.0.1:5173
- 통합 화면/API: http://127.0.0.1:8000
- 상태 확인: http://127.0.0.1:8000/api/health
- API 문서: http://127.0.0.1:8000/docs

휴대폰의 마이크·카메라와 PWA 설치를 시험할 때는 HTTPS가 필요합니다. 백엔드가
켜진 상태에서 별도 터미널로 Quick Tunnel을 엽니다.

```powershell
cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000
```

출력된 `https://...trycloudflare.com` 주소를 두 휴대폰에서 동일하게 사용합니다.
Quick Tunnel 주소는 재시작할 때 바뀌므로 고정 사용은 Render 배포 주소 또는
고정 Cloudflare Tunnel을 사용해야 합니다.

## 환경변수

실제 값은 `.env`와 Render 환경변수에만 저장합니다.

| 변수 | 역할 |
|---|---|
| `OPENAI_API_KEY`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | OpenAI/Gemini 호환 답변 생성 |
| `LLM_FAST_MODEL`, `LLM_FAST_REASONING_EFFORT` | 실시간 통화용 저지연 모델·추론 수준 |
| `ELEVENLABS_API_KEY` | 실시간 STT와 가족별 음성 복제·TTS |
| `ANAM_API_KEY` | 확정된 가족 사진으로 아바타 생성 및 실시간 립싱크 |
| `ANAM_AVATAR_ID` | 무료 배포 DB가 초기화될 때 기본 대웅 아바타를 복구하는 선택 값 |
| `TURN_URLS`, `TURN_SHARED_SECRET` | 휴대폰 NAT·공유기 격리 환경의 사람 통화 중계(coturn REST) |
| `STORAGE_DIR` | 배포 환경의 영속 DB·비공개 자산 저장 위치 |
| `TTS_BRIDGE_TOKEN` | 선택적 로컬 MuseTalk 브리지 인증 |
| `DEMO_SEED_MODE=high_volume` | 공개 데모 DB에 30일 통화와 세 환자의 7·8·9월 통화·비교·정서 주제 예시를 적재 |

사진·목소리가 승인될 때 공급자 ID를 가족별로 SQLite에 저장하며 브라우저에는
짧은 세션 토큰만 전달합니다. 영속 디스크가 없는 데모 배포만 기본 대웅의
`ANAM_AVATAR_ID`를 복구 값으로 사용할 수 있습니다. 전체 예시는
[`.env.example`](.env.example)에 있습니다.

## 얼굴 연령 변화

제품에 포함된 검증 완료 데모 타임라인은
`8 → 9 → 11 → 13 → 15 → 16 → 17 → 20 → 23 → 26 → 29 → 31 → 32`이며,
`data/faces/morph.mp4`로 재생됩니다.

AI Hub 71415·528 데이터를 사용하는 차세대 실험은 별도입니다. 현재 사진만으로
추정하는 모드와 어린 시절 사진을 보조 근거로 쓰는 모드를 분리하고, 직접·순차·
FRAN 가이드·어린 사진 보조 후보를 같은 조건에서 비교합니다. 한 사람에 대한
Identity LoRA와 어린 사진 보조 LoRA 학습, 후보 4개 생성, 블라인드 검토 화면까지
실행됐습니다. 다만 후보가 실제 8세처럼 보이는지와 자동 추천 순위가 사람의 판단을
잘 예측하는지는 아직 검증 중이며, 봉인한 실제 8세 사진은 최종 평가 전까지 생성과
순위 학습에 사용하지 않습니다. 자세한 현재 상태와 실행 명령은
[`docs/face_aging_system.md`](docs/face_aging_system.md), 세부 연구 로그는
[`docs/aihub71415_pipeline.md`](docs/aihub71415_pipeline.md)를 참고하세요.

## 배포

운영 환경은 [`render.yaml`](render.yaml)의 단일 Docker 웹 서비스입니다. Docker
빌드가 Vite 프론트엔드를 생성하고 FastAPI가 정적 파일과 API를 함께 제공합니다.
상태 확인 경로는 `/api/health`이며, `main` 브랜치 CI 통과 후 Render 자동 배포를
사용합니다. 공개 데모에서는 `DEMO_SEED_MODE=high_volume`으로 빈 DB에 데이터를
넣고, 기존 영속 DB에는 누락된 비교 환자·세 환자의 2026년 7~9월 통화·박순자
어르신 정서 주제 예시를 전용 접두사로 보완합니다. 고길동은 알츠하이머 치매와
고혈압, 박순자는 루이소체 치매와 파킨슨증, 이정호는 혈관성 치매와 뇌경색 과거력의
관찰 특성이 서로 다르게 보이도록 구성했습니다. 사용자 통화는 데모 접두사로
삭제하거나 교체하지 않습니다.

Galaxy S24에서는 Chrome으로 운영 HTTPS 주소를 열어 확인합니다. CSS 기준 폭
360px에서도 가로 스크롤이 없어야 하며, 홈 화면에 설치하면 manifest 설정에 따라
세로형 standalone PWA로 실행됩니다. 배포 전에는 아래 검증과 함께 360×780
뷰포트에서 시작·가족·오늘·추억함·통화·설정·담당자 화면을 확인합니다.

## 검증

```bash
# 백엔드 — 328개
python -m pytest tests/ -q
python -m unittest discover -s tests      # pytest 없이도 같은 결과

# 프론트엔드 — 121개
cd frontend && npm test
cd frontend && npm run build              # 실행 시점 오류는 빌드가 못 잡는다

# 안전 레이어 — 시나리오 37개 (서버 없이 LLM만 호출)
python tools/eval.py --sleep 5
python tools/eval.py --raw --sleep 5      # safety 없이 비교

# 통화 흐름 (API 서버가 켜져 있어야 함)
python tools/call_flow.py

# 브라우저 두 대 흐름. 해시 직행 주소가 개발 모드 전용이라 Vite 개발
# 서버(5173)를 겨눕니다. playwright 가 필요합니다.
cd frontend && node e2e/two_devices.mjs http://127.0.0.1:5173
```

Windows PowerShell에서는 `python` 대신 `.\.venv\Scripts\python.exe`를 사용합니다.

`backend/prompts/persona_system.md`나 `backend/safety.py`를 고칠 때마다
`tools/eval.py`를 돌립니다. 평가·데모 보조 명령은
[`docs/demo_script.md`](docs/demo_script.md)에 있습니다.
사람 통화 구조와 STUN/TURN 결정 근거는
[`docs/call_transport_decision.md`](docs/call_transport_decision.md)에 기록했습니다.

## 저장소 구조

```
backend/        FastAPI + SQLite (27테이블). analysis/ 는 관찰 분류·집계
frontend/       React 19 + Vite. src/screens 는 역할별 화면
tools/          운영·평가 스크립트. face_aging/ 은 연령 변환, setup/ 은 설치
tests/          pytest 46파일
docs/           설계 근거와 연구 로그
data/           시드·얼굴/음성 자산 (런타임 DB와 비공개 녹음은 제외)
```

어느 파일이 무슨 일을 하는지는 [`CLAUDE.md`](CLAUDE.md)의 "현재 구조"에 있습니다.

## 주요 문서

- [`docs/architecture.md`](docs/architecture.md): 통화 한 번이 처음부터 끝까지 어떻게 도는가
- [`docs/service_definition.md`](docs/service_definition.md): 문제 정의와 MVP 범위
- [`docs/analysis_design.md`](docs/analysis_design.md): 발화 분류·집계·판정 원칙
- [`docs/call_transport_decision.md`](docs/call_transport_decision.md): WebRTC와 AI 인계
- [`docs/face_aging_system.md`](docs/face_aging_system.md): 얼굴 생성·검증·후보 선택
- [`docs/aihub71415_pipeline.md`](docs/aihub71415_pipeline.md): 연령 변환 연구 로그
- [`docs/demo_script.md`](docs/demo_script.md): 시연 준비와 핵심 장면

외부 모델과 데이터는 각 원본 라이선스와 AI Hub 이용 조건을 따릅니다.
