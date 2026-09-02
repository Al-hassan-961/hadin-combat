# HADIN-COMBAT API Reference

## WebSocket Endpoint

### `WS /ws/{client_id}`

Establishes a bidirectional real-time session. `client_id` is any unique
string (the web client generates one like `web-abc123def`).

### Client → Server

**Binary message (JPEG frame)**

A raw JPEG byte payload is decoded to a frame and processed.

**JSON control messages**

| `type` | Payload | Description |
|---|---|---|
| `reset` | `{}` | Reset difficulty to `0.4`, clear frame counter, coach & fatigue state. |
| `set_profile` | `{"profile": "aggressive"}` | Switch the sparring-partner AI profile mid-session. |
| `feedback_text` | `{"text": "..."}` | Echo a custom coaching message back. |

Profiles: `balanced`, `aggressive`, `counter_puncher`, `defensive`,
`pressure_fighter` (see `app/profiles.py`).

Example:
```json
{ "type": "reset" }
{ "type": "set_profile", "profile": "counter_puncher" }
```

### Server → Client

**`hello`** — sent immediately after connection:
```json
{
  "type": "hello",
  "backend": "cpp",
  "message": "HADIN-COMBAT ready. Begin your session."
}
```

**`frame`** — sent per processed frame:
```json
{
  "type": "frame",
  "client_id": "web-abc123def",
  "keypoints": [
    { "x": 312.0, "y": 90.0, "score": 0.97 }
  ],
  "opponent": [
    { "x": 0.42, "y": 0.31, "score": 1.0 }
  ],
  "feedback": {
    "grade": "B",
    "score": 82,
    "notes": ["Center your shoulders over your hips for better balance."]
  },
  "movements": [
    { "type": "jab", "side": "left", "quality": 81, "advice": ["..."] }
  ],
  "coach": {
    "last": { "type": "jab", "side": "left", "quality": 81, "advice": ["..."] },
    "counts": { "jab": 3, "front_kick": 1 },
    "total_strikes": 4,
    "tempo_per_s": 1.2,
    "advice": ["Extend the jab fully, then snap it straight back to your guard."]
  },
  "difficulty": 0.41,
  "latency_ms": 31.2,
  "backend": "cpp"
}
```

**`movements`** — detected martial-arts techniques this frame (basic:
`jab`, `cross`, `hook`, `uppercut`, `front_kick`, `roundhouse_kick`,
`knee_raise`; complex: `superman_punch`, `spinning_backfist`, `axe_kick`,
`question_mark_kick`; plus `block`, `guard`, `stance`), each with `side`,
`quality` (0–100), a `confidence` score (0–1) and `advice`.

**`coach`** — session coaching summary: `last` (most recent technique),
`counts` (per-technique counters), `total_strikes`, `tempo_per_s` (strikes per
second over the recent window) and `advice` (rotating professional coaching tips).

**`fatigue`** — real-time fatigue: `score` (0–100), `level`
(`fresh`/`moderate`/`fatigued`), per-component `components`
(`snap`, `reaction`, `stability`) and recovery `advice`.

**`profile`** — human-readable label of the active sparring-partner AI profile.

**`feedback`** — custom message:
```json
{ "type": "feedback", "message": "Keep your guard up!" }
```

**`reset_ack`** — after a reset:
```json
{ "type": "reset_ack", "difficulty": 0.4 }
```

**`ack`** — generic acknowledgment:
```json
{ "type": "ack", "received": "feedback_text" }
```

**`error`** — error notification:
```json
{ "type": "error", "message": "Bad JSON" }
```

---

## REST Endpoints

### `GET /`

Serves `website/index.html` (the mobile-first frontend).

### `GET /api/stats`

Returns backend status, active sessions, and athlete profile:

```json
{
  "backend": "cpp",
  "sessions": [
    { "client_id": "web-abc123def", "frames": 120, "fps": 14.9,
      "difficulty": 0.41, "style_tags": [] }
  ],
  "profile": {
    "athlete_id": "local",
    "total_sessions": 0,
    "total_rounds": 0,
    "win_rate": 0.5,
    "avg_response_ms": 0.0,
    "progress_score": 0.0
  },
  "latency_target_ms": 50
}
```

### `GET /api/history`

Completed session summaries (bounded) plus personalised improvement
suggestions:

```json
{
  "history": [
    { "client_id": "web-x", "duration_s": 180, "frames": 1800,
      "profile": "counter_puncher", "techniques": { "jab": 24, "hook": 9 },
      "total_strikes": 33, "fatigue": 62 }
  ],
  "improvement": [
    "Your most-used technique is jab (24 reps) — drill it into sharper, faster reps.",
    "Sessions end quite fatigued — add short breaks between rounds."
  ]
}
```

### `GET /api/session/{client_id}`

Live view of an active session (`live: true`) or the last matching completed
session (`live: false`); `404` if not found.

### Static assets

- The website (incl. `/dashboard.html`) is served at the site root.

---

## Data Schemas

### Keypoint

| Field | Type | Description |
|---|---|---|
| `x` | number | x coordinate (pixels, absolute) |
| `y` | number | y coordinate (pixels, absolute) |
| `score` | number | confidence 0..1 |

### Opponent point

| Field | Type | Description |
|---|---|---|
| `x` | number | normalized x 0..1 |
| `y` | number | normalized y 0..1 |
| `score` | number | always `1.0` for generated poses |

### Feedback

| Field | Type | Description |
|---|---|---|
| `grade` | string | `A`, `B`, or `C` |
| `score` | number | 0..100 quality score |
| `notes` | string[] | coaching tips |

### AthleteProfile

| Field | Type | Description |
|---|---|---|
| `athlete_id` | string | unique id |
| `total_sessions` | integer | completed sessions |
| `total_rounds` | integer | total rounds fought |
| `win_rate` | number | 0..1 |
| `avg_response_ms` | number | average reaction time (ms) |
| `progress_score` | number | 0..1 improvement trend |
