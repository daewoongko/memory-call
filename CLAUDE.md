# Repository working notes

This file is a compact guide for coding agents and contributors. Product setup and operation
belong in `README.md`; the final presentation flow belongs in `docs/demo_runbook.md`.

## Non-negotiable product contracts

- This is support software, not a diagnostic or treatment system.
- Never invent a visit, call, location, meal, medication state, or shared memory.
- Only `verified` memories with `conversation_allowed=true` may ground a factual reply.
- A new recall stays unverified until a guardian reviews it.
- If the elder asks who is speaking, describe it as a memory call prepared by the family; do
  not claim the AI is literally that person.
- Reports must expose the underlying utterance and must not convert sparse observations into a
  diagnosis or a perfectly uniform score.
- Human-call failure falls back to the AI call. Anam failure falls back to ElevenLabs audio.

## Final demo invariants

The single source for presentation data is `tools/demo_config.py`.

- Date: 2026-08-31
- Calls: 40
- Duration: 160 minutes
- Grounded memory: `mem_016`, 대웅이와 강가 공놀이
- Morph: 24.2 seconds, ages 8·9·10·11·12·15·17·20·24·28
- TTS rate: 0.93
- Wait audio: `frontend/src/assets/waiting-nature-guide-24.2s.mp3`

When one of these changes, update the source constant or media metadata first, then update
tests and docs. Do not introduce another hard-coded presentation date.

## Code map

- `backend/api.py`: API composition and static mounts
- `backend/conversation.py`: live turn lifecycle
- `backend/persona.py`: prompt and grounded context
- `backend/safety.py`: deterministic safety pass
- `backend/invites.py`: call state machine and the 24.2-second intro contract
- `backend/report.py`: evidence-backed guardian analytics
- `frontend/src/App.jsx`: client call-state orchestration
- `frontend/src/useSpeech.js`: STT/TTS lifecycle and 0.93 rate
- `frontend/src/callTransport.js`: WebRTC boundary
- `frontend/src/screens/RoleOnboardingScreen.jsx`: multi-photo and age-candidate flow
- `data/faces/`: canonical approved demo face bundle
- `tools/seed_gildong_demo.py`: deterministic presentation database

## Data and media rules

- `data/faces/` is the only tracked canonical Daewoong face bundle.
- `data/personas/` is runtime/private storage. Do not commit generated persona directories.
- Keep API keys, `.env`, SQLite files, raw private recordings, QC exports, and experiments out
  of Git.
- Approved runtime media is stored as regular Git objects so CI and deployment do not depend
  on Git LFS download quotas.
- Do not replace approved media without checking its duration, dimensions, checksum metadata,
  and client/server timing constants.

## Before committing

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Set-Location frontend
npm test
npm run build
```

For deployment changes also build the Docker image. Preserve user data and unrelated local
changes; never rewrite Git history or force-push as part of ordinary cleanup.
