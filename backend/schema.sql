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
    active          INTEGER DEFAULT 1
);

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
    guardian_actions   TEXT,   -- JSON
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);
