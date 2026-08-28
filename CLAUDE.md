# CLAUDE.md — 이 저장소에서 작업하는 규칙

**서비스가 무엇이고 왜 그렇게 만들었는지는 [`README.md`](README.md) 하나에
있습니다.** 이 파일은 중복하지 않고, 코드를 고칠 때 필요한 것만 적습니다.

## 작성자 선호 (중요)

- **한국어로 응답할 것**
- 페어 프로그래밍 스타일. 어떤 파일의 어디를 왜 고치는지 명시
- 각 단계마다 브라우저/터미널에서 직접 테스트한 뒤 다음으로 진행
- 규칙 기반 로직 우선. LLM 호출은 인터페이스를 깔끔히 분리해둘 것
- 틀린 방향으로 가면 직접적으로 지적해달라 (돌려 말하지 말 것)

## 고치기 전에 읽을 것

- 기능의 **왜**를 바꾼다 → `README.md` §1 서비스 정의를 먼저 고친다
- 안전 규칙을 건드린다 → `README.md` §2, 그리고 **반드시 `tools/eval.py` 를 돌린다**
- 맥락 제공을 넓힌다 → 기능보다 **eval 시나리오를 먼저** 넣는다
- 통화 전송을 바꾼다 → `README.md` §6 의 논거와 뒤집는 조건을 본다

## 절대 어기면 안 되는 규칙 (AI 응답 기준)

1. 등록된 일정에 없는 방문·통화 약속 생성 금지
2. `verified` 기억만 사실로 사용. `partial` 은 불확실성 표현 필수
3. 처음 듣는 기억은 사실 확정 금지, 회상 유도만
4. `prohibited` 기억(고인, 가족 갈등)은 먼저 꺼내지 않되 거짓말도 금지
5. 의료·복약 판단이나 용량 변경·추가 복용·중단 권고 금지
6. 정서적 독점 유도 금지 ("나한테만 전화해" 류)
7. 정체성을 직접 물으면 명시적 거짓말 금지
8. 금융·법률 요청 수행 금지

> **맥락은 등록된 사실에서만 나온다. 등록되지 않은 것은 맥락으로도 말하지 않는다.**

---

## 파일 지도

★ 는 고칠 때 특히 조심할 파일입니다. 흐름은 `README.md` §4 를 봅니다.

```
backend/
  api.py                        엔드포인트 전부. 역할별 화면이 여기만 본다
  db.py / schema.sql            SQLite 27테이블. load_context() 가 단일 조회 창구
  prompts/persona_system.md     페르소나 규칙. 1차 방어
  persona.py                    통화용 fast / 리포트용 full 두 벌의 프롬프트
  llm.py                        ★ LLM 단일 창구. 스트리밍·429 백오프·
                                FastReply 스키마 검증·모핑 중 워밍업
  safety.py                     ★ 규칙 검사 계층. 2차 방어
  conversation.py               빠른 답변(동기) / 리포트 메타데이터(백그라운드)
  care.py                       LLM 관찰 후보를 원문 대조로 검증
  analysis/observation_catalog.py  ★ 8도메인 76신호 3티어 단일 정의
  analysis/rates.py             분모 인식 비교. 표본 미달이면 비교하지 않는다
  invites.py                    ★ 호출 상태. 받았는가·거절인가·무응답인가
  memories.py / schedules.py    기억 승인, 확정 일정만 대화에 넣기
  report.py                     통화·기간 리포트. 집계는 규칙, 문장만 LLM
  accounts.py / linking.py      계정·동의·기기 연동(6자리 코드)
  signaling.py                  WebRTC SDP/ICE 중계. 내용은 해석하지 않는다
  elevenlabs_stt.py             실시간 STT 1회용 토큰
  elevenlabs_tts.py             ★ TTS 단일 창구
  persona_voice.py              가족별 IVC/PVC 음성 등록
  anam.py / persona_avatar.py   ★ 아바타 단일 창구. 공급자 ID 는 서버에만
  tts_proxy.py / stt.py         선택적 MuseTalk 브리지 / 서버 전사 폴백
  storage.py                    저장 경로 단일 창구 (STORAGE_DIR)
  age_*.py (9개)                연령 앵커 계획·검증 정책
  admin.py / face_quality.py    페르소나·사진 관리, 입력 품질 검사

frontend/src/
  App.jsx                       ★ 어르신 상태머신 idle→calling→human|incall→ended
  api.js                        서버 호출 단일 창구
  device.js                     ★ 이 기기가 누구인가. device_id 발급·보관
  useIncomingCall.js            ★ 가족 수신 폴링 (heartbeat 겸용)
  callTransport.js              ★ 사람↔사람 미디어 단일 창구 (WebRTC)
  anamTransport.js              아바타 세션 연결
  useSpeech.js                  음성 인식·합성 오케스트레이션
  useRealtimeTranscription.js   ElevenLabs 실시간 STT + 서버 전사 폴백
  speechPipeline.js             첫 문장이 나오는 즉시 TTS 시작하는 청크 분할
  screens/                      어르신: Family, Calling, Call, HumanCall, Summary
                                보호자: Child, GuardianCallOverlay, ReportTabs,
                                        FamilyAnalysisReport,
                                        FamilyMemoryClothesline(회상 승인)
                                공통:   Login, Role, RoleOnboarding, Link, NetTest
  styles.css                    4790행. 죽은 규칙이 아직 남아 있다(아래 참고)
frontend/e2e/two_devices.mjs    ★ 브라우저 두 개로 폰 두 대 흐름 확인

tools/
  serve.py / start.py           개발 서버 / 배포 진입점(DB 없으면 시드)
  init_db.py / demo_reset.py    DB 생성 / 시연 준비
  eval.py + scenarios.json      ★ 안전 레이어 자동 평가 37개
  eval_reports.py               리포트 품질 평가
  chat.py / call_flow.py        터미널 대화 / 호출 흐름 4가지
  check_key.py                  쓸 수 있는 모델 확인
  seed_*.py (6개)               데모 데이터. start.py 가 경로로 부른다
  prep_faces.py                 ★ backend/admin.py 가 경로로 부른다
  age_estimate_3ddfa.py         ★ backend/age_growth.py 가 부른다
  age_estimate_mivolo.py        ★ backend/age_secondary.py 가 부른다
  make_morph.py / make_loops.py / fix_loop.py / validate_morph.py
  prepare_selected_morph_keyframes.py / rife_ort_ctypes.py
  tts_bridge.py / musetalk_server.py / musetalk_trial.py
  elevenlabs_clone_voice.py     음성 연결 수동 진단
  benchmark_*.py / diagnose_*.py / audit_*.py / e2e_care_calls.py
  migrate_evidence.py           배포된 구 DB 용 일회성 마이그레이션(멱등)
  face_aging/                   얼굴 나이 변환 생성·검증·AI Hub 실험 30개
  setup/                        Windows 설치 스크립트 (*.ps1)
```

### 옮기면 안 되는 파일

프로덕션이 **경로로** 부르기 때문입니다. 파일 몇 개 줄이려다 배포를 깨뜨립니다.

| 파일 | 부르는 곳 |
|---|---|
| `tools/seed_*.py` | `tools/start.py` (배포 부팅) |
| `tools/prep_faces.py` | `backend/admin.py` |
| `tools/age_estimate_3ddfa.py` | `backend/age_growth.py` |
| `tools/age_estimate_mivolo.py` | `backend/age_secondary.py` |

---

## 개발 명령

```bash
source .venv/bin/activate

python tools/serve.py                    # 터미널 1: API 서버 (8000)
cd frontend && npm run dev               # 터미널 2: 화면 (5173)

python -m pytest tests/ -q               # 백엔드 328개
cd frontend && npm test                  # 프론트 121개
cd frontend && npm run build             # 실행 시점 오류는 빌드가 못 잡는다

python tools/eval.py --sleep 5           # 안전 시나리오 37개
python tools/eval.py --raw --sleep 5     # safety 없이 (비교용)
python tools/call_flow.py                # 호출 4가지 (서버가 켜져 있어야 함)

# 해시 직행이 개발 모드 전용이라 빌드 결과(8000)가 아니라 5173 을 겨눈다
cd frontend && node e2e/two_devices.mjs http://127.0.0.1:5173
```

전체 실행·환경변수·화면 주소는 `README.md` §7, 검증은 §8 을 봅니다.

**`persona_system.md` 나 `safety.py` 를 고칠 때마다 `eval.py` 를 돌립니다.**

## 주의

- `.env` 는 절대 커밋하지 않는다 (`.gitignore` 에 등록됨)
- 공급자 ID(ElevenLabs voice_id, Anam avatar_id)는 서버 DB 에만 둔다
- 무료 티어 LLM 은 요청 내용이 모델 개선에 쓰일 수 있다. 실제 가족 데이터가
  들어가는 시점부터는 유료 티어로 옮긴다

## 아직 남은 정리거리

- `frontend/src/styles.css` 에 JSX 가 그리지 않는 클래스가 **381개** 남아 있다.
  살아 있는 규칙과 얽혀 있어 지우려면 화면을 눈으로 비교해야 한다. 빌드도
  테스트도 잘못 지운 것을 알려주지 않는다
- `backend/api.py`(2399행)·`report.py`(2352행)·`useSpeech.js`(1124행)는 크다.
  쪼개는 것은 정리가 아니라 리팩터링이라 별도 작업으로 둔다
- `frontend/src/api.js` 의 미사용 export 9개는 서버 엔드포인트와 1:1 이라 남겼다
- `data/personas/persona_godaewoong/aligned/age_path_v3_skin_normalized/` 14개는
  코드 참조가 없다

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
`frontend/e2e/two_devices.mjs` 가 실제 브라우저 두 개로 이 구간을 본다.

**떠 있는 버튼이 아래 버튼을 삼킨다.** `.wide-display-dock` 은
`position: absolute` 로 콘텐츠 위에 떠 있는데, 412px(갤럭시 S24) 폭에서
보호자 온보딩의 "기본 말투로 바로 시작"과 겹쳐 탭이 독으로 갔다. **버튼은
멀쩡히 보이고 `disabled` 도 아니어서** 눌러도 아무 일이 없는 것으로만
나타났다. `document.elementFromPoint()` 로 히트 타겟을 찍어야 보인다.
여백을 주는 것으로는 부족했다 — 본문이 길면 스크롤 위치에 따라 버튼이
다시 독 아래로 들어간다. 폰 폭에서는 독을 띄우지 말고 세로 흐름의 마지막
칸으로 내려야 겹칠 자리 자체가 없어진다.

**heartbeat 은 화면이 꺼지면 같이 꺼져야 한다.** 보호자 수신 폴링이 곧
"지금 전화를 받을 수 있다"는 신고인데, `visibilitychange` 에서 다시 켜기만
하고 멈추지는 않아서 잠긴 폰이 계속 신고했다. 서버는 받을 사람이 있다고 믿고
벨을 15초 내내 울렸고, **증상은 "6초로 안 줄어든다" 하나뿐이었다.** 어르신이
아무도 받지 않을 전화를 끝까지 들여다보는 것이 진짜 손해다. 신고를 멈추면
`DEVICE_ALIVE_SEC` 안에 서버가 알아차린다. `GET /api/devices` 로 서버가
어느 기기를 살아 있다고 보는지 확인할 수 있다 — 폰에서 개발자 도구 없이
"왜 벨이 안 오지"를 볼 유일한 창이다.

**같은 페르소나의 보호자 기기가 여러 대면 하나만 깨어 있어도 길게 운다.**
PC 브라우저에 `#child` 탭을 열어둔 채 폰을 꺼도 대기 시간이 줄지 않는다.
의도된 동작이지만 시연 중에는 헷갈리므로 `GET /api/devices` 를 먼저 본다.

**CSS 축약형은 뒤에서 조용히 덮는다.** `padding-bottom` 을 고쳤는데 뒤쪽
미디어 쿼리의 `padding` 축약형이 되돌려 놓았다. 계산된 값을 직접 읽기
전까지는 규칙이 적용된 줄 알았다.

**브라우저 음성 합성은 세 가지를 방어해야 한다.** 목소리 목록이 늦게
로드되면 엉뚱한 음성이 나가고, `cancel()` 직후 `speak()` 하면 무음이 되고,
`onend` 가 유실되면 다음 동작이 영원히 오지 않는다.

**GPU 하나를 두 프로세스가 나눠 쓰면 캐싱 할당자가 독이 된다.** PyTorch 는
해제한 블록을 드라이버에 돌려주지 않고 재사용하려고 쥐고 있다. 한 프로세스
안에서는 최적화지만 Chatterbox 는 별개 프로세스라 그 풀을 볼 수 없다.
MuseTalk 가 8GB 를 물고 있는 동안 여유 VRAM 이 959MiB 로 떨어졌고, 남는
메모리가 실제로 있는데도 Chatterbox 가 호스트 메모리로 밀려 2.6초 합성이
13.6초가 됐다. 렌더가 끝날 때마다 `empty_cache()` 로 반환해야 한다.
**증상이 "느려짐"으로만 나타나서 OOM 처럼 보이지 않는다.**

**(갱신) TTS를 ElevenLabs API로 옮기면서 이 항목은 해소됐다.** Chatterbox가
로컬 GPU에서 완전히 빠지고 MuseTalk 혼자 GPU를 쓰므로 위 VRAM 경합은 더
이상 일어나지 않는다. `empty_cache()` 반환 자체는 MuseTalk 내부에 여전히
남아있고(다른 프로세스와 나눠 쓰지 않아도 손해가 없어 굳이 뺄 이유가 없었다),
`tools/tts_bridge.py`는 이제 MuseTalk 하나만 관리한다. 립싱크(MuseTalk)도
API로 옮기는 것은 별도 검토 사항이며, CLAUDE.md의 SadTalker/D-ID 관련 결정
(위 "명시적으로 하지 않기로 한 것")은 그대로 유효하다 — 상용 실시간 립싱크
API는 로컬 4초보다 느릴 위험이 커서 함부로 되돌리지 않는다.

**프레임을 파일로 내렸다 다시 읽으면 추론보다 비싸다.** PNG 저장 + ffmpeg
2패스가 GPU 추론(2.5초)보다 오래 걸려 립싱크가 8.7초였다. 원시 프레임을
ffmpeg stdin 으로 흘려 한 번에 먹싱하면 3.9초가 된다. 인코딩이 추론과
겹쳐 돌아가는 것이 덤이다.

**모델 워밍업은 실제 배치를 채울 만큼 길어야 한다.** 0.4초 무음으로
워밍업했더니 batch 32 경로가 안 데워져서 첫 실제 발화만 10.3초가 걸렸다.
통화의 첫 마디가 가장 느린 건 최악이다.

**PowerShell 5.1 은 한글 본문을 UTF-8 로 보내지 않는다.** 스모크 테스트가
`-Body $jsonString` 으로 보낸 한국어가 깨져서, 엉뚱한 소리를 읽은 영상을
"통과"로 판정할 뻔했다. `[Text.Encoding]::UTF8.GetBytes()` 로 명시한다.
`Invoke-WebRequest -OutFile` 이 `-PassThru` 없이 null 을 반환하는 것도
같이 물린다.

**죽은 코드는 조용히 죽어 있지 않고 테스트를 인질로 잡는다.**
`App.jsx` 의 `chooseAIWhileWaiting` 은 정의만 되고 호출되는 곳이 없었는데,
`apiElderScope.test.js` 가 그 함수 안의 문구(`if (takeoverInFlight.current)
return`)를 정규식으로 검사하고 있었다. 그래서 **죽은 코드가 초록불을
유지하는 근거**가 되어 있었고, 지우는 순간 테스트가 깨졌다. 테스트가
"동작"이 아니라 "문자열"을 검사하면 이런 일이 생긴다. 게다가 그 함수는
`takeover_reason` 으로 `"user_selected_ai"` 를 보내는데 이 값은
`call_invites` 의 CHECK 제약에 없다 — **실행됐다면 DB 오류가 났을 코드가
테스트를 통과시키고 있었다.** 문구를 검사할 때는 반드시 실제로 도는
경로에 고정한다.

**폴더를 하나 만들면 `parents[1]` 이 전부 거짓말이 된다.** `tools/` 를
역할별로 나누면서 33개 파일의 `ROOT = Path(__file__).resolve().parents[1]`
이 저장소 루트가 아니라 `tools/` 를 가리키게 됐다. 이런 스크립트는 GPU 와
라이선스 데이터가 있어야 돌아서 여기서 실행해 볼 수 없다. 그래서 **파일을
import 하지 않고 `ROOT` 대입문만 `ast` 로 떼어내 격리 실행**해서 저장소
루트가 맞는지 33개 전부 확인했다. 실행할 수 없는 코드도 경로 계산은
검증할 수 있다.

**"한 단계만 올라간다"는 자가복구는 자가복구가 아니다.**
`age_mask_preview.py` 는 `backend/` 를 못 찾으면 `ROOT.parent` 로 한 번만
올라갔다. 폴더가 하나 더 생기자 그대로 실패했다. 찾을 때까지 도는
`while` 로 바꿔야 다음 이동에도 살아남는다.

**옮기면 안 되는 파일은 프로덕션이 경로로 부르는 파일이다.**
`tools/start.py` 는 배포 부팅에서 `seed_*.py` 를 절대경로로 실행하고,
`backend/admin.py` 는 `tools/prep_faces.py` 를, `age_growth.py` 와
`age_secondary.py` 는 각각 추정 스크립트를 그렇게 부른다. 정리하다가
이 여섯 개를 건드리면 파일 몇 개 줄이려다 배포를 깨뜨린다. 정리 대상에서
먼저 빼 놓는다.

**검증 도구가 상수를 베껴 두면 조용히 낡는다.** 벨 시간을 24초로 통일한
뒤에도 `tools/call_flow.py` 는 15초·6초를, `e2e/two_devices.mjs` 는 `.countdown`
과 `"6초"` 를 그대로 들고 있었다. 둘 다 오래 빨간불이었고, 아무도 안 봐서
빨간 줄 알지도 못했다. 지금은 서버가 응답에 실어 보내는 `intro_duration_sec`
을 쓰거나, 아예 절대값 대신 **"받을 기기가 있든 없든 같은 시간을 기다린다"**
는 불변식을 검사한다. 숫자를 두 곳에 적으면 언젠가 갈라진다.

**없는 선택자로 부정 검사를 하면 영원히 통과한다.**
`check(!(await page.locator(".guardian-call-timer").count()), "통화 중에
갇히지 않는다")` 가 그랬다. 그 클래스는 CSS 에만 남고 JSX 는 더 이상 그리지
않아서 `count()` 가 항상 0 이었고, 그래서 **통화가 실제로 안 끊겨도 통과**했다.
부정 검사를 쓸 때는 그 선택자가 성공 경로에서 한 번은 잡히는지 먼저 본다.
e2e 선택자를 JSX 와 통째로 대조하면 이런 것이 한 번에 드러난다.

**e2e 는 빌드 결과가 아니라 개발 서버를 겨눠야 한다.** `#elder`, `#child`
같은 해시 직행은 `import.meta.env.DEV` 로 막혀 있어서 `npm run build` 결과에
대고 돌리면 로그인 화면에서 멈춘다. 예전 문서의
`npm run build && node e2e/two_devices.mjs http://127.0.0.1:8000` 은 해시가
막히기 전에 쓰던 명령이다.

**끊기 버튼은 두 번 눌러야 한다.** 어르신이 잘못 눌러 통화가 끊기는 것을
막으려고 `CallEndConfirm` 을 거치게 해 두었다. e2e 가 한 번만 누르고 있어서
통화가 그대로 이어졌고, 그 뒤 시나리오가 전부 "대기 화면이 안정되지 않음"
으로 무너졌다. 증상이 원인에서 세 단계 떨어진 곳에 나타난다.
