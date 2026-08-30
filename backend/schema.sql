-- 기억이음 Call MVP 스키마
-- 단일 노인 · 단일 페르소나 기준. 다중 가족 지원은 MVP 범위 밖.

PRAGMA foreign_keys = ON;

-- 앱 계정과 역할별 최초 설정. 휴대전화 소유권 확인은 SMS 공급자가 붙는
-- 경계에서 수행하고, 서버에는 간편번호의 PBKDF2 해시와 세션 해시만 남긴다.
CREATE TABLE IF NOT EXISTS app_users (
    user_id       TEXT PRIMARY KEY,
    phone         TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    pin_salt      TEXT NOT NULL,
    pin_hash      TEXT NOT NULL,
    phone_verified_at TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_app_sessions_user
    ON app_sessions(user_id, expires_at);

CREATE TABLE IF NOT EXISTS user_role_onboarding (
    user_id       TEXT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('elder','child')),
    current_step  TEXT NOT NULL DEFAULT 'intro',
    progress_data TEXT NOT NULL DEFAULT '{}',
    completed_at  TEXT,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS consent_records (
    consent_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('elder','child')),
    elder_id        TEXT,
    consent_type    TEXT NOT NULL,
    consent_version TEXT NOT NULL,
    consent_mode    TEXT NOT NULL DEFAULT 'self',
    accepted_at     TEXT NOT NULL,
    revoked_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_consent_user_role
    ON consent_records(user_id, role, accepted_at);

CREATE TABLE IF NOT EXISTS elder_profiles (
    elder_id            TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    preferred_call_name TEXT,
    birth_date          TEXT,
    -- 지남력 사실. 둘 다 "평소" 정보이며 통화 시점의 현재 위치가 아니다.
    -- 비어 있으면 프롬프트에 "미등록"으로 나가고 AI 는 거주지를 말하지 않는다.
    residence_type      TEXT,
    household_members   TEXT,   -- JSON 배열 [{"name": ..., "relation": ...}]
    diagnosis_label     TEXT,   -- 등록된 진단명. 서비스가 추론하지 않는다.
    care_baseline       TEXT,   -- JSON: 평소 관찰 기준
    medical_cautions    TEXT,   -- JSON: 의료진에게 보고할 주요 변화
    speech_wait_time_ms INTEGER DEFAULT 2000,
    hearing_support     INTEGER DEFAULT 0,
    vision_support      INTEGER DEFAULT 0,
    anxiety_triggers    TEXT,   -- JSON 배열
    calming_phrases     TEXT,   -- JSON 배열
    frequent_questions  TEXT,   -- JSON 배열
    emergency_contacts  TEXT,   -- JSON 배열
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personas (
    persona_id         TEXT PRIMARY KEY,
    elder_id           TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    display_name       TEXT NOT NULL,
    relationship_type  TEXT,
    elder_calls_family TEXT,
    family_calls_elder TEXT,
    tone               TEXT,
    frequent_phrases   TEXT,   -- JSON 배열
    forbidden_phrases  TEXT,   -- JSON 배열
    sensitive_policy   TEXT,
    call_style_code    TEXT,   -- CEML 같은 4글자 통화 성향 코드
    call_style_name    TEXT,
    call_style_scores  TEXT,   -- JSON 축별 점수
    call_style_answers TEXT,   -- JSON 문항별 선택값
    avatar_performance_style TEXT NOT NULL DEFAULT 'calm',
    active             INTEGER DEFAULT 1,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 가족별 복제 음성 상태. ElevenLabs 식별자는 서버에서만 사용하고 화면에는
-- 등록 단계와 누적 시간만 내보낸다. IVC를 먼저 활성화한 뒤 PVC 표본을
-- 점진적으로 모으더라도 현재 통화 음성이 끊기지 않게 둘을 따로 보관한다.
CREATE TABLE IF NOT EXISTS persona_voice_profiles (
    persona_id          TEXT PRIMARY KEY REFERENCES personas(persona_id),
    ivc_voice_id        TEXT,
    pvc_voice_id        TEXT,
    active_voice_type   TEXT CHECK (active_voice_type IN ('ivc','pvc')),
    active_voice_id     TEXT,
    voice_status        TEXT NOT NULL DEFAULT 'unregistered' CHECK (voice_status IN (
        'unregistered','ivc_recording','ivc_ready','pvc_collecting',
        'pvc_verification_required','pvc_training','pvc_ready','failed'
    )),
    recorded_seconds    REAL NOT NULL DEFAULT 0,
    consent_at          TEXT,
    approved_at         TEXT,
    verification_status TEXT NOT NULL DEFAULT 'not_started',
    pvc_training_status TEXT NOT NULL DEFAULT 'not_started',
    voice_version       INTEGER NOT NULL DEFAULT 1,
    script_version      TEXT NOT NULL DEFAULT 'ko-care-v1',
    last_error          TEXT,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persona_voice_samples (
    sample_id         TEXT PRIMARY KEY,
    persona_id        TEXT NOT NULL REFERENCES personas(persona_id),
    phase             TEXT NOT NULL CHECK (phase IN ('ivc','pvc')),
    prompt_id         TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    original_name     TEXT,
    mime_type         TEXT,
    duration_seconds  REAL NOT NULL,
    quality           TEXT, -- JSON: 브라우저에서 측정한 무음·클리핑 지표
    usable            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_persona_voice_samples
    ON persona_voice_samples(persona_id, phase, created_at);

-- Anam custom avatar generated from the family member's confirmed current photo.
-- Provider ids are server-only and are never returned by public profile APIs.
CREATE TABLE IF NOT EXISTS persona_avatar_profiles (
    persona_id         TEXT PRIMARY KEY REFERENCES personas(persona_id),
    avatar_id          TEXT,
    avatar_model       TEXT NOT NULL DEFAULT 'cara-4',
    source_photo_name  TEXT,
    source_sha256      TEXT,
    avatar_status      TEXT NOT NULL DEFAULT 'unregistered' CHECK (
        avatar_status IN ('unregistered','creating','ready','failed')
    ),
    last_error         TEXT,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id            TEXT PRIMARY KEY,
    elder_id             TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    title                TEXT NOT NULL,
    description          TEXT,
    date_text            TEXT,
    location             TEXT,
    participants         TEXT,   -- JSON 배열
    status               TEXT NOT NULL CHECK (status IN
                            ('verified','partial','unverified','prohibited')),
    conversation_allowed INTEGER DEFAULT 1,
    note                 TEXT,
    source_call_id       TEXT,   -- 통화 중 새로 발견된 기억이면 그 통화
    photo_url            TEXT,   -- 가족이 직접 올린 실제 사진
    happened_year        INTEGER, -- 추억이 일어난 연도. 모르면 NULL
    created_at           TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_elder ON memories(elder_id, status);

CREATE TABLE IF NOT EXISTS calls (
    call_id      TEXT PRIMARY KEY,
    elder_id     TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    persona_id   TEXT REFERENCES personas(persona_id),
    -- 통화 당시 표시값. 나중에 페르소나 이름이 바뀌어도 과거 리포트는 유지한다.
    counterpart_name     TEXT,
    counterpart_relation TEXT,
    report_title         TEXT,
    call_type    TEXT DEFAULT 'ai' CHECK (call_type IN ('direct','ai','ai_to_direct')),
    started_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at     TEXT,
    duration_sec INTEGER,
    end_reason   TEXT,
    status       TEXT DEFAULT 'active'
                 CHECK (status IN ('requested','active','ended','failed'))
);
CREATE INDEX IF NOT EXISTS idx_calls_elder_started
    ON calls(elder_id, started_at);

-- 통화 중 발화 한 줄. Gemini가 신고한 JSON 필드를 그대로 보관한다.
CREATE TABLE IF NOT EXISTS utterances (
    utterance_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id           TEXT NOT NULL REFERENCES calls(call_id),
    seq               INTEGER NOT NULL,
    speaker           TEXT NOT NULL CHECK (speaker IN ('elder','ai')),
    transcript        TEXT,
    intent            TEXT,
    certainty         TEXT,
    used_memory_ids   TEXT,   -- JSON 배열
    unverified_recall TEXT,   -- JSON 객체
    -- 비진단적 인지·정서·생활 관찰과 실제 응답에 사용한 근거·지원 행동.
    care_data          TEXT,   -- JSON 객체
    grounding         TEXT,
    safety_flags      TEXT,   -- JSON 배열. safety.py가 잡아낸 위반
    was_rewritten     INTEGER DEFAULT 0,
    latency_ms        INTEGER,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_utt_call ON utterances(call_id, seq);

-- 위험 · 모핑 · 실제 가족 연결 등 통화 중 이벤트
CREATE TABLE IF NOT EXISTS call_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES calls(call_id),
    -- 이벤트를 만든 할아버지 발화. 보호자 화면의 인용은 여기서 나온다.
    utterance_id    INTEGER REFERENCES utterances(utterance_id),
    -- 모델이 신고한 응답. 추적·디버깅용.
    ai_utterance_id INTEGER REFERENCES utterances(utterance_id),
    -- safety_block 은 더 이상 쓰지 않는다. 옛 행 때문에 값은 남겨 둔다.
    event_type      TEXT NOT NULL CHECK (event_type IN
                    ('risk','morph','handoff','safety_block')),
    payload      TEXT,   -- JSON 객체
    acknowledged INTEGER DEFAULT 0,
    acknowledged_at TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_evt_call ON call_events(call_id, event_type);

-- 통화 중 나온 미확인 회상에 대한 보호자의 판단.
-- 한 번 처리한 것은 다시 묻지 않기 위해 결정을 남긴다 (명세 FR-05).
-- 보호자 기기와 어르신 기기를 잇는 일회용 코드.
-- 계정과 비밀번호 대신 짧은 숫자를 쓴다. 어르신이 입력하기 쉬워야 한다.
CREATE TABLE IF NOT EXISTS link_codes (
    code       TEXT PRIMARY KEY,
    elder_id   TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 통화를 걸거나 받을 수 있는 기기.
-- 페르소나는 "AI 가 흉내낼 가족"이고, 이 표는 "그 가족의 실제 기기"다.
-- 둘을 persona_id 로 이어야 어르신이 고른 사람에게 벨이 간다.
-- last_seen_at 은 보호자 화면의 수신 폴링이 갱신한다. 별도 heartbeat 는 두지
-- 않는다. 폴링하고 있다는 사실 자체가 살아 있다는 뜻이기 때문이다.
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    elder_id     TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    role         TEXT NOT NULL CHECK (role IN ('elder', 'guardian')),
    persona_id   TEXT REFERENCES personas(persona_id),
    label        TEXT,
    last_seen_at TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_device_persona
    ON devices(persona_id, last_seen_at);

-- 잠금 화면에서도 가족에게 위험 알림을 전달하기 위한 Web Push 구독.
-- endpoint와 암호화 키는 브라우저가 발급하며 비밀 VAPID 개인키는 환경변수에만 둔다.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint    TEXT PRIMARY KEY,
    device_id  TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_device ON push_subscriptions(device_id);

-- 호출 한 건. "누가 누구에게 걸었고, 받았는가"를 서버가 판정하기 위한 표.
--
-- 이 표가 없을 때 AI 대리통화는 대리가 아니었다. 어르신 기기 안의 15초
-- 타이머가 끝나면 보호자가 받았든 말든 무조건 AI 로 넘어갔기 때문이다.
-- 받지 않았다는 사실을 기록할 곳이 있어야 "대신 받았다"가 성립한다.
--
-- takeover_reason 은 AI 가 왜 대신 받았는지를 남긴다. 이 값이 있어야 보호자
-- 리포트에서 "거절 3건 / 무응답 5건"을 구분할 수 있다. state 는 ai_takeover
-- 하나로 덮이므로 사유를 따로 보관해야 한다.
CREATE TABLE IF NOT EXISTS call_invites (
    invite_id    TEXT PRIMARY KEY,
    elder_id     TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    persona_id   TEXT REFERENCES personas(persona_id),
    from_device  TEXT,   -- 건 기기 (어르신)
    to_device    TEXT,   -- 실제로 받은 기기. answer 시점에 확정된다
    state        TEXT NOT NULL CHECK (state IN
                 ('ringing','answered','declined','timeout',
                  'ai_takeover','ended','cancelled')),
    -- 벨이 울릴 시간. 서버가 정해서 내려보낸다. 클라이언트에 15 를 박아 두면
    -- 받을 기기가 없을 때도 똑같이 기다리게 된다.
    ring_timeout_sec REAL NOT NULL DEFAULT 14.8,
    -- 걸 때 살아 있는 보호자 기기가 하나도 없었는가.
    -- 타임아웃 사유를 no_device 와 timeout 으로 가르는 데 쓴다.
    no_live_device   INTEGER DEFAULT 0,
    takeover_reason  TEXT CHECK (takeover_reason IN
                     ('declined','timeout','no_device','transport_failed',
                      'media_permission_denied')),
    ai_call_id   TEXT REFERENCES calls(call_id),
    purpose      TEXT NOT NULL DEFAULT 'family',
    alert_type   TEXT,
    alert_evidence TEXT,
    source_call_id TEXT REFERENCES calls(call_id),
    created_at   TEXT NOT NULL,
    answered_at  TEXT,
    ended_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_invite_ring
    ON call_invites(persona_id, state, created_at);
CREATE INDEX IF NOT EXISTS idx_invite_elder
    ON call_invites(elder_id, created_at);

-- 두 기기가 P2P 를 붙이려고 주고받는 신호(SDP, ICE 후보).
-- 서버는 내용을 해석하지 않고 방(room)별로 전달만 한다.
--
-- 지금은 #nettest 진단 화면만 쓴다. 통화에 P2P 를 붙일 때 room 을 invite_id
-- 로 두면 같은 표를 그대로 쓸 수 있다. 통화 상태(call_invites)와 섞지 않는
-- 이유는, 신호는 오갈 때마다 행이 쌓이고 호출 상태는 하나로 유지되어야 해서
-- 수명이 다르기 때문이다.
CREATE TABLE IF NOT EXISTS signal_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room       TEXT NOT NULL,
    sender     TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('offer', 'answer', 'ice')),
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_room ON signal_messages(room, id);

-- 어떤 망에서 P2P 가 붙었는지. 발표에서 "재보고 정했다"고 말하려면 기록이
-- 남아야 한다 (README.md §6).
CREATE TABLE IF NOT EXISTS nettest_results (
    result_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    room        TEXT,
    label       TEXT,             -- "집 와이파이", "LTE ↔ 와이파이" 처럼 사람이 적는다
    connected   INTEGER NOT NULL,
    route       TEXT,             -- host | srflx | relay
    symmetric   INTEGER,          -- 1 대칭, 0 아님, NULL 판별 못 함
    stun_ok     INTEGER,
    elapsed_ms  INTEGER,
    round_trip_ms INTEGER,
    user_agent  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recall_reviews (
    utterance_id INTEGER PRIMARY KEY REFERENCES utterances(utterance_id),
    decision     TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    memory_id    TEXT,
    note         TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports (
    report_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id            TEXT NOT NULL UNIQUE REFERENCES calls(call_id),
    summary            TEXT,
    repeated_questions TEXT,   -- JSON
    new_recalls        TEXT,   -- JSON. 보호자 확인 대기
    risk_summary       TEXT,   -- JSON
    care_summary       TEXT,   -- JSON. 인지·정서·생활 관찰
    meaningful_moments TEXT,   -- JSON. 마음 기록/Life Archive 후보
    family_mentions    TEXT,   -- JSON. 등록된 가족 이름의 실제 발화 횟수
    guardian_actions   TEXT,   -- JSON
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 마음 기록의 실제 발화로부터 만든 감성 이미지 후보.
-- candidate 단계에서는 사실 재현물이 아니라 '기억에서 영감을 받은 상상 이미지'로만 노출한다.
-- 보호자가 사실 관계를 확인하면 approved, 부정하면 rejected로 남긴다.
CREATE TABLE IF NOT EXISTS heart_artworks (
    artwork_id          TEXT PRIMARY KEY,
    call_id             TEXT NOT NULL REFERENCES calls(call_id),
    source_utterance_id INTEGER NOT NULL REFERENCES utterances(utterance_id),
    memory_id           TEXT REFERENCES memories(memory_id),
    status              TEXT NOT NULL CHECK (status IN ('candidate','approved','rejected')),
    image_url           TEXT NOT NULL,
    source_quote        TEXT NOT NULL,
    alt_text            TEXT NOT NULL,
    caption             TEXT NOT NULL,
    prompt_summary      TEXT,
    diary_date          TEXT,
    diary_title         TEXT,
    mood_label          TEXT,
    storyline_id        TEXT,
    storyline_chapter   INTEGER NOT NULL DEFAULT 1,
    previous_artwork_id TEXT REFERENCES heart_artworks(artwork_id),
    continuity_note     TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_heart_artworks_call
    ON heart_artworks(call_id, status, created_at);
