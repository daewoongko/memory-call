# memory-call

치매 환자가 잃어가는 기억과 현재의 맥락을 가족 기반 AI 영상통화로 연결하고, 보호자의 반복적인 설명·안심 부담을 줄이는 돌봄 MVP입니다. 가족의 얼굴·목소리·추억을 사용하며, 확인되지 않은 것을 사실로 만들지 않는 안전 레이어가 핵심입니다. 저장소에는 완성된 연령 변화 타임라인과 RIFE 모핑 영상이 포함되어 있으며, FastAPI와 React 화면에서 바로 재생할 수 있습니다.

서비스의 문제 정의와 범위는 [`docs/service_definition.md`](docs/service_definition.md)를 보세요.

> 이 공개 저장소에는 프로젝트 소유자가 공개를 승인한 얼굴 사진, 음성 샘플, 개인화 LoRA 가중치가 Git LFS로 포함됩니다. 다른 사람의 생체정보를 추가할 때는 반드시 당사자의 명시적 동의를 받으세요. API 키와 런타임 DB는 포함하지 않습니다.

## 완성된 연령 변화 파이프라인

최종 타임라인은 `8 → 9 → 11 → 13 → 15 → 16 → 17 → 20 → 23 → 26 → 29 → 31 → 32`입니다.

- FLUX.2 Klein Inpaint: 얼굴 마스크 기반 과거 모습 생성
- Identity LoRA: 현재 사진 5장으로 개인 신원 특징 유지
- FRAN 성장 prior: 어린 연령 구간의 구조 변화 가이드
- InsightFace: 신원 유사도와 1차 연령 근거
- MiVOLO: 독립적인 2차 연령 근거
- 3DDFA-V2: 포즈 정규화 3D 얼굴 구조의 보조 근거
- 사람 검토: 경계 후보와 최종 키프레임 승인
- RIFE: 승인 키프레임 사이를 직접 timestep 보간

정확한 나이 점수는 단독 자동 탈락 기준이 아니라 검토 근거로 사용합니다. 어린 구간에서는 신원 임계값을 연령에 맞게 완화하되, 직전 승인 키프레임과의 연속성 및 모핑 품질을 함께 확인합니다.

최종 결과:

- 영상: `data/faces/morph.mp4`
- 검증: `data/faces/morph.validation.json`
- QC 시트: `data/faces/morph_qc.png`
- 키프레임: `data/faces/aligned/age_path_final/`
- 해상도/길이: 768×1024, 30fps, 852프레임, 28.4초

## 로컬 실행

Git LFS 파일을 먼저 받습니다.

```powershell
git lfs install
git lfs pull
```

백엔드:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python tools\serve.py --no-reload
```

프론트엔드(별도 터미널):

```powershell
cd frontend
npm ci
npm run dev
```

- 화면: http://127.0.0.1:5173
- API 상태: http://127.0.0.1:8000/api/health
- API 문서: http://127.0.0.1:8000/docs

`.env.example`을 `.env`로 복사한 뒤 `LLM_API_KEY`를 로컬에서만 설정하세요. `.env`와 `data/memory_call.sqlite`는 Git에서 제외됩니다.

### 인지·정서 케어 리포트 데모 데이터

제공된 8개 평가 발화를 날짜·시각·가족 이름·관계가 있는 8개의 독립 통화로
미리 넣으려면 프로젝트 루트의 별도 터미널에서 실행합니다. 기존 실제 통화는
유지하고 `demo_care_` 통화만 교체하며 Gemini API는 호출하지 않습니다.

```powershell
.\.venv\Scripts\python.exe tools\seed_care_demo.py
```

7일과 30일 누적 화면의 차이를 보려면, 세 영역과 위험·반복·마음 기록이 고르게
포함된 추가 통화 10건도 넣습니다. 날짜는 최근 30일에 분산되어 있고 각 통화는
어르신 2회 발화와 AI 2회 응답으로 구성됩니다.

```powershell
.\.venv\Scripts\python.exe tools\seed_care_history.py
```

발표용 고빈도 화면은 최근 30일에 매일 30통 이상을 넣는 스크립트를 사용합니다.
같은 질문을 한 통화 안에서 2~4회 실제 발화로 저장하므로 월간 꺾은선과
통화별 발화·상태 버블 지도를 함께 확인할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe tools\seed_high_volume_demo.py
```

실행 후 브라우저를 새로고침하고 `보호자 화면 → 케어 리포트`를 엽니다.
마음 기록, 인지·정서·행동 관찰, 가족 이름 반복, 위험 신호와 전체 대화를 확인할
수 있습니다.

8개 통화 후 리포트가 시나리오별 기대 관찰·직접 발화 근거·보호자 확인 항목을
모두 갖췄는지는 다음 명령으로 자동 검사합니다. Gemini는 호출하지 않습니다.

```powershell
.\.venv\Scripts\python.exe tools\eval_reports.py
```

보호자 화면의 오각형 관찰 지도는 같은 기간 안의 관찰 건수를 상대적으로
보여주는 시각화이며, 치매 단계나 임상적 중증도 점수가 아닙니다.

### 마음 기록 이미지의 확인 흐름

통화 중 나온 추억은 곧바로 실제 장면으로 확정하지 않습니다.

1. 통화의 실제 발화를 `마음 기록 후보`로 보관합니다.
2. 확인 전 미리보기는 `기억에서 영감을 받은 상상 이미지`라고 표시합니다.
3. 보호자가 가족 기억 화면에서 `사실이에요`를 선택하면 확인된 기억 ID와
   이미지가 연결됩니다.
4. 이후 가족 기억 보관함과 마음 리포트에서는 `확인된 기억 기반` 이미지로
   재사용합니다.
5. 기억을 대화 금지로 바꾸거나 삭제하면 이미지도 통화와 리포트에서 제외됩니다.

현재 고향 냇가 데모 그림은
`frontend/public/heart-art/hometown-stream-v1.png`에 있으며, 실제 제품에서는
3단계 승인 시점에 가족이 보완한 인물·장소·시기 정보로 최종 이미지를 비동기로
생성하는 방식이 적합합니다.

대표 3종(위치 혼동·낙상·고향 회상)을 실제 Gemini 응답부터 안전검사, DB 저장,
통화 종료, 상세·마음 리포트 생성까지 확인하려면 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe tools\e2e_care_calls.py
```

이 검사는 미영(딸)과 정훈(아들)을 고길동 어르신의 데모 가족으로 등록합니다.
브라우저 마이크 입력과 TTS·영상 재생은 실제 기기에서 별도로 확인합니다.

## ElevenLabs 음성 클론

배포된 앱의 복제 음성은 ElevenLabs API로 직접 만듭니다. 로컬 GPU나 터널이 필요 없으며, Render 백엔드가 `backend/elevenlabs_tts.py`를 통해 바로 호출합니다.

최초 한 번 `data/voice/reference.wav`를 ElevenLabs Instant Voice Cloning에 등록합니다.

```powershell
.\.venv\Scripts\python.exe tools\elevenlabs_clone_voice.py --name "가족 목소리"
```

출력된 `voice_id`를 `.env`의 `ELEVENLABS_VOICE_ID`에, 발급받은 키를 `ELEVENLABS_API_KEY`에 넣습니다. Render 대시보드의 환경변수에도 같은 값을 저장한 뒤 재배포하세요. **립싱크(MuseTalk) 없이 순수 음성 통화는 이 설정만으로 완전히 동작하며, 로컬 PC를 켜 둘 필요가 없습니다.**

## MuseTalk 립싱크 (선택, 로컬 GPU 필요)

립싱크 영상은 선택 기능입니다. 원할 때만 CUDA GPU가 있는 PC에서 `tools/tts_bridge.py`를 켜서 붙입니다. 브리지는 이제 MuseTalk 1.5 워커 하나만 `127.0.0.1:8002`에 띄우고 Cloudflare Quick Tunnel로 노출합니다. 백엔드가 ElevenLabs로 만든 오디오를 이 터널의 `/render`로 전달하면 입 모양에 맞춘 MP4를 돌려받습니다. 로컬 서버는 `127.0.0.1`에만 열리며, 터널 등록·상태 확인·립싱크 렌더 모두 동일한 Bearer 비밀키를 요구합니다. 임시 터널 주소는 짧은 TTL heartbeat로 갱신됩니다.

최초 한 번 다음 순서로 준비합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_musetalk_runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_cloudflared.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\configure_tts_bridge_secret.ps1 -CopyToClipboard
```

마지막 명령은 임의 비밀키를 `.env`에 저장하고 값은 출력하지 않은 채 클립보드에만 복사합니다. Render 대시보드에서 서비스의 환경변수 `TTS_BRIDGE_TOKEN`에 같은 값을 한 번 저장한 뒤 재배포하세요. `render.yaml`의 `sync: false` 설정 때문에 비밀키는 Git에 들어가지 않습니다.

모델을 기본 위치가 아닌 곳에 두었다면 `.env`에 `MEMORY_CALL_MUSETALK_DIR`를 지정합니다. 아바타 캐시가 없거나 불완전하면 브리지가 시작 시점에 실패하므로, MuseTalk이 통화 중에 대화형 프롬프트로 멈추는 일은 없습니다.

배포가 완료되면 터미널 하나에서 브리지 관리자를 실행합니다. 관리자가 로컬 MuseTalk 워커와 Quick Tunnel을 함께 시작하고, 주소 등록·heartbeat·비정상 종료 후 재시작까지 담당합니다.

```powershell
.\.venv\Scripts\python.exe tools\tts_bridge.py --render-url https://memory-call.onrender.com
```

VS Code에서는 `Terminal → Run Task → memory-call: TTS bridge (Render)`를 선택해도 됩니다. 이 터미널과 PC/GPU가 켜져 있을 때만 배포 앱의 립싱크 영상이 동작합니다. 개발 중 브라우저 음성을 명시적으로 허용하려는 경우에만 `frontend/.env.local`에 `VITE_TTS_BROWSER_FALLBACK=true`를 설정하세요.

Heartbeat는 브리지가 켜져 있는 동안 Render 무료 인스턴스를 활성 상태로 유지합니다. 따라서 PC에서 브리지를 오래 켜 둘수록 Render의 월 무료 실행 시간이 함께 사용됩니다.

**립싱크는 선택 경로입니다.** 워커가 없거나 바쁘거나 실패하면 프론트가 같은 ElevenLabs 음성 WAV로 조용히 전환하고 통화는 그대로 이어집니다. 데모 중 GPU가 흔들려도 대화가 끊기지 않게 하기 위한 것이며, 얼굴이 정지 화면으로 돌아갈 뿐입니다. MuseTalk이 이제 GPU를 혼자 쓰므로, 예전에 Chatterbox와 나눠 쓰며 겪던 VRAM 경합(음성 합성이 2.6초에서 13.6초로 느려지던 문제)은 더 이상 발생하지 않습니다.

## 프로덕션 빌드

Docker 이미지는 React 프로덕션 빌드, FastAPI, 최종 얼굴 자산과 모핑 영상을 하나로 묶습니다.

```bash
docker build -t memory-call .
docker run --rm -p 8000:8000 -e LLM_API_KEY="your-key" memory-call
```

브라우저에서 http://localhost:8000 을 엽니다. `render.yaml`은 Render Docker 배포용이며, GitHub `main`의 CI 검사가 통과하면 연결된 Render 서비스가 자동 배포되도록 설정되어 있습니다. 실제 키는 Render 환경변수에만 저장합니다.

## 연령 생성 환경

웹 앱 실행에는 `requirements.txt`만 필요합니다. GPU 기반 재생성·검증은 별도 환경으로 분리되어 있습니다.

- `requirements-flux2.txt`: FLUX.2 후보 생성
- `requirements-flux2-train.txt`: Identity LoRA 재학습
- `requirements-age.txt`: InsightFace 기반 검증
- `requirements-reaging.txt`: FRAN 구조 가이드

대형 원본 모델은 저장소에 포함하지 않습니다. 기본 모델 위치는 `%USERPROFILE%\Models`이며 다음 환경변수로 바꿀 수 있습니다.

- `MEMORY_CALL_MODELS_DIR`
- `FLUX2_COMPONENTS_DIR`
- `FLUX2_FP8_CHECKPOINT`
- `REAGING_MODEL_DIR` / `REAGING_MODEL_PATH`

## RIFE 영상 재생성

```powershell
.\.venv\Scripts\python.exe tools\make_morph.py
.\.venv\Scripts\python.exe tools\validate_morph.py --strict
powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_morph.ps1
```

`install_morph.ps1`은 검증된 `morph.next.mp4`만 설치하고 기존 파일을 타임스탬프 백업합니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run build
```

## 라이선스 메모

RIFE ONNX 모델과 관련 라이선스는 `backend/models/rife/`에 함께 보존합니다. FLUX.2 및 외부 연령 모델은 각각의 원본 라이선스와 이용 조건을 따릅니다.
