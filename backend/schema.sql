-- 기억이음 Call MVP 스키마
-- 단일 노인 · 단일 페르소나 기준. 다중 가족 지원은 MVP 범위 밖.

PRAGMA foreign_keys = ON;

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
    active             INTEGER DEFAULT 1,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
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
    created_at           TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_elder ON memories(elder_id, status);

CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    elder_id    TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    title       TEXT NOT NULL,
    date        TEXT NOT NULL,   -- YYYY-MM-DD
    time        TEXT,            -- HH:MM
    note        TEXT,
    confirmed   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS medications (
    schedule_id     TEXT PRIMARY KEY,
    elder_id        TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    medication_name TEXT NOT NULL,
    dosage_text     TEXT,
    scheduled_time  TEXT,        -- HH:MM
    meal_relation   TEXT CHECK (meal_relation IN ('before','after','none')),
    days_of_week    TEXT,        -- JSON 배열
    indication      TEXT,        -- 처방 목적(보호자·담당자 입력, 진단 자동 추정 금지)
    monitoring_points TEXT,      -- JSON 배열. 담당자가 관찰할 항목
    review_interval_days INTEGER DEFAULT 14,
    escalation_criteria TEXT,    -- 약 변경 지시가 아니라 의료진 보고 기준
    active          INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS medication_reviews (
    review_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    elder_id        TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    schedule_id     TEXT NOT NULL REFERENCES medications(schedule_id),
    review_date     TEXT NOT NULL,
    severity        INTEGER NOT NULL DEFAULT 0 CHECK (severity BETWEEN 0 AND 3),
    observed_flags  TEXT,
    note            TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_medication_reviews
    ON medication_reviews(elder_id, schedule_id, review_date);

-- 약과 관찰 신호의 연결은 담당자가 명시적으로 등록한다. 시스템이 약 이름만
-- 보고 부작용이나 인과 관계를 자동 추정하지 않는다.
CREATE TABLE IF NOT EXISTS medication_signal_links (
    schedule_id     TEXT NOT NULL REFERENCES medications(schedule_id),
    signal          TEXT NOT NULL,
    link_level      TEXT NOT NULL CHECK (link_level IN ('monitoring','escalation')),
    criterion_text  TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (schedule_id, signal, link_level)
);
CREATE INDEX IF NOT EXISTS idx_medication_signal_links
    ON medication_signal_links(schedule_id, signal);

-- 복약 기록. 노인이 직접 입력하지 않고 통화 중 말로 확인한 결과가 쌓인다.
CREATE TABLE IF NOT EXISTS medication_logs (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    elder_id      TEXT NOT NULL REFERENCES elder_profiles(elder_id),
    schedule_id   TEXT NOT NULL REFERENCES medications(schedule_id),
    call_id       TEXT,
    utterance_id  INTEGER REFERENCES utterances(utterance_id),
    taken_date    TEXT NOT NULL,   -- YYYY-MM-DD
    status        TEXT NOT NULL CHECK (status IN
                     ('USER_CONFIRMED','UNCLEAR','REFUSED','DUPLICATE_SUSPECTED')),
    evidence_text TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_medlog_day
    ON medication_logs(elder_id, taken_date, schedule_id);

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
    used_schedule_ids TEXT,   -- JSON 배열
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

-- 위험 · 복약 · 모핑 등 통화 중 이벤트
CREATE TABLE IF NOT EXISTS call_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES calls(call_id),
    -- 이벤트를 만든 할아버지 발화. 보호자 화면의 인용은 여기서 나온다.
    utterance_id    INTEGER REFERENCES utterances(utterance_id),
    -- 모델이 신고한 응답. 추적·디버깅용.
    ai_utterance_id INTEGER REFERENCES utterances(utterance_id),
    -- safety_block 은 더 이상 쓰지 않는다. 옛 행 때문에 값은 남겨 둔다.
    event_type      TEXT NOT NULL CHECK (event_type IN
                    ('risk','medication','morph','handoff','safety_block')),
    payload      TEXT,   -- JSON 객체
    acknowledged INTEGER DEFAULT 0,
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
    medication_summary TEXT,   -- JSON
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
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_heart_artworks_call
    ON heart_artworks(call_id, status, created_at);
