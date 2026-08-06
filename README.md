# memory-call

가족의 얼굴과 목소리, 기억을 이용해 영상 통화를 돕는 치매 돌봄 MVP입니다. 현재 저장소에는 완성된 연령 변화 타임라인과 RIFE 모핑 영상이 포함되어 있으며, FastAPI와 React 화면에서 바로 재생할 수 있습니다.

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
