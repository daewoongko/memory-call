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

| 화면 | 주 사용 목적 |
|---|---|
| 어르신 | 가족에게 전화하거나, 연결되지 않을 때 가족 기반 AI 통화를 이어감 |
| 가족 | 직접 통화, 오늘의 마음 기록·가족 추억함 확인, 얼굴·목소리 설정 |
| 요양원 담당자 | 어르신별 관찰 리포트·정서 주제·복약·일정·인계를 근거와 함께 확인 |

통화는 두 경로로 동작합니다.

- 사람 통화: WebRTC P2P(STUN only)로 음성·영상을 연결합니다. 미디어 연결이
  실패하면 어르신에게 오류를 노출하지 않고 AI 통화로 인계합니다.
- AI 통화: ElevenLabs 실시간 STT → OpenAI 호환 LLM 답변 → 서버 안전 검사 →
  ElevenLabs 가족별 음성 → Anam 가족별 아바타 순서입니다. Anam이 없거나
  실패해도 같은 음성으로 통화가 계속됩니다.

MuseTalk은 로컬 GPU에서만 사용하는 선택적 립싱크 대체 경로입니다. 일반 통화와
배포 앱에는 필요하지 않습니다. 통화 전 권한 확인, 화면 Wake Lock, PWA 설치,
API 비캐시 service worker가 포함되어 있습니다.

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
| `STORAGE_DIR` | 배포 환경의 영속 DB·비공개 자산 저장 위치 |
| `TTS_BRIDGE_TOKEN` | 선택적 로컬 MuseTalk 브리지 인증 |
| `DEMO_SEED_MODE=high_volume` | 공개 데모 DB에 30일 통화·비교 환자·정서 주제 예시를 최초 1회 적재 |

전역 `ANAM_AVATAR_ID`나 전역 가족 `voice_id`는 사용하지 않습니다. 사진·목소리가
승인될 때 공급자 ID를 가족별로 생성해 SQLite에 저장하며, 브라우저에는 짧은
세션 토큰만 전달합니다. 전체 예시는 [`.env.example`](.env.example)에 있습니다.

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
넣고, 기존 영속 DB에는 누락된 비교 환자와 박순자 어르신 정서 주제 예시만 한 번
추가합니다. 사용자 통화는 데모 접두사로 삭제하거나 교체하지 않습니다.

Galaxy S24에서는 Chrome으로 운영 HTTPS 주소를 열어 확인합니다. CSS 기준 폭
360px에서도 가로 스크롤이 없어야 하며, 홈 화면에 설치하면 manifest 설정에 따라
세로형 standalone PWA로 실행됩니다. 배포 전에는 아래 검증과 함께 360×780
뷰포트에서 시작·가족·오늘·추억함·통화·설정·담당자 화면을 확인합니다.

## 검증

```powershell
# 백엔드
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 프론트엔드
cd frontend
npm test
npm run build
```

평가·데모 보조 명령은 [`docs/demo_script.md`](docs/demo_script.md)에 있습니다.
사람 통화 구조와 STUN only 결정 근거는
[`docs/call_transport_decision.md`](docs/call_transport_decision.md)에 기록했습니다.

## 주요 문서

- [`docs/service_definition.md`](docs/service_definition.md): 문제 정의와 MVP 범위
- [`docs/analysis_design.md`](docs/analysis_design.md): 발화 분류·집계·판정 원칙
- [`docs/call_transport_decision.md`](docs/call_transport_decision.md): WebRTC와 AI 인계
- [`docs/face_aging_system.md`](docs/face_aging_system.md): 얼굴 생성·검증·후보 선택
- [`docs/demo_script.md`](docs/demo_script.md): 시연 준비와 핵심 장면

외부 모델과 데이터는 각 원본 라이선스와 AI Hub 이용 조건을 따릅니다.
