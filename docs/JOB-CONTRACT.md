# Kontrak Job Suba — v0.1

Dokumen ini mendefinisikan format data job dan checkpoint agar pipeline CLI/Colab dapat melanjutkan pekerjaan tanpa mengulang chunk yang sudah selesai. Ini rancangan awal; implementasi wajib memvalidasi dan versioning manifest.

## 1. Direktori job

```text
<job-dir>/
├── job.json                 # Manifest dan status
├── source/                  # File sumber atau metadata referensi
├── chunks/
│   ├── 000000-000600/
│   │   ├── audio.wav        # Opsional, sesuai kebijakan retensi job
│   │   ├── asr.json
│   │   ├── ocr.json
│   │   ├── fused.json
│   │   └── chunk.json       # Status, checksum, timer
│   └── ...
├── transcript.srt           # Hasil bahasa sumber (jika relevan)
├── translated_id.srt        # Hasil terjemahan
├── glossary.json            # Istilah/nama (opsional)
└── logs/
    └── events.jsonl         # Log peristiwa tanpa rahasia
```

File sementara Colab VM (`/content`) tidak dianggap durable. Checkpoint/artefak yang diperlukan untuk resume wajib disalin ke storage persisten job setelah tiap chunk atau batch selesai.

## 2. Status job dan chunk

Status job:

```text
created → probing → ready → running → translating → completed
                            ↘ failed (resumable bila ada chunk pending/retryable)
                            ↘ needs_input (mis. ROI atau bahasa ambigu)
                            ↘ cancelled
```

Status chunk:

```text
pending → running → done
                  ↘ retryable_failed → running
                  ↘ failed
```

- `done` hanya setelah output ditulis atomik, dibaca ulang/validasi, dan checksum disimpan.
- `retryable_failed` untuk gangguan jaringan/runtime/timeout; `failed` untuk input/konfigurasi yang tidak dapat diperbaiki dengan retry.
- `resume` hanya melewati chunk `done` bila checksum input, pipeline, model/version dan konfigurasi yang memengaruhi hasil masih cocok.
- Ketika konfigurasi relevan berubah, tandai artefak turunan stale dan proses ulang hanya tahap yang terdampak (misal glossary/prompt berubah → translate saja).

## 3. Skema manifest minimum

```json
{
  "schema_version": 1,
  "job_id": "uuid",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z",
  "status": "created",
  "source": {
    "kind": "file",
    "path": "source/input.mp4",
    "sha256": "...",
    "duration_seconds": null,
    "video": {"width": null, "height": null},
    "audio_stream_index": null,
    "subtitle_streams": []
  },
  "pipeline": {"selected": "3", "reason": "user_override"},
  "languages": {
    "audio_source": "zh",
    "hardsub_source": "en",
    "target": "id"
  },
  "models": {
    "asr": {"name": "large-v3-turbo", "engine": "faster-whisper", "compute_type": "float16"},
    "ocr": {"name": "PP-OCR", "engine": "PaddleOCR"},
    "translator": {"provider": "configured-provider", "model": "configured-model"}
  },
  "chunk_seconds": 600,
  "chunks": [],
  "glossary_path": "glossary.json",
  "outputs": [],
  "timings": {},
  "errors": []
}
```

Catatan keamanan: manifest tidak berisi API key, token, cookie, atau header autentikasi. Provider/model boleh dicatat tanpa kredensial.

## 4. Skema chunk

```json
{
  "id": "000000-000600",
  "core_start_seconds": 0.0,
  "core_end_seconds": 600.0,
  "process_start_seconds": 0.0,
  "process_end_seconds": 605.0,
  "status": "pending",
  "attempts": 0,
  "input_sha256": "...",
  "config_fingerprint": "...",
  "artifacts": {
    "asr": {"path": "chunks/000000-000600/asr.json", "sha256": null},
    "ocr": {"path": "chunks/000000-000600/ocr.json", "sha256": null},
    "fused": {"path": "chunks/000000-000600/fused.json", "sha256": null}
  },
  "timings_seconds": {"decode": null, "asr": null, "ocr": null, "fuse": null, "translate": null},
  "error": null
}
```

`core_*` defines the output interval; `process_*` may include overlap context. Merge/export removes duplicate overlap by retaining only segments attributed to a chunk core (or deterministically resolving duplicates by timestamp/content).

## 5. Atomic writes and checksums

1. Write output to a sibling temp file (e.g. `asr.json.tmp`).
2. Flush/close; validate JSON/SRT structure; calculate SHA-256.
3. Rename temp file to final path atomically where supported.
4. Update `chunk.json` and then `job.json` atomically.
5. Sync artifacts to durable storage before marking chunk `done`.

If a run stops between output write and manifest update, resume validates artifact and may safely adopt it; it must not assume unverified partial output is complete.

## 6. Structured segments

```json
{
  "id": "seg-000001",
  "start_seconds": 1.25,
  "end_seconds": 3.8,
  "text": "recognized or extracted text",
  "source": "asr",
  "confidence": null,
  "language": "ko",
  "conflict": false,
  "review_required": false
}
```

Confidence scales vary across OCR/ASR engines; preserve provider-native score and its interpretation rather than comparing raw numbers across engines as if calibrated.

## 7. Event log

`events.jsonl`: one JSON object per line, e.g. timestamp, job_id, chunk_id, stage, event, duration_seconds, status, error_code, message. Do not log source contents by default, secrets, signed URLs, cookies, or raw provider request/response headers. Keep user-visible errors actionable but redact credentials and private paths where appropriate.

## 8. SRT merge contract

- Offset local chunk timestamps by `process_start_seconds` or source media offset.
- Retain core-range segments; resolve overlap duplicates deterministically.
- Sort ascending by start time, then end time; re-number sequentially at final render.
- Validate `start < end`, timestamps parse, UTF-8 encoding, monotonic ordering, and no unintended overlap.
- Do not silently truncate or merge semantically distinct speech/subtitle events to satisfy line limits; flag readability issues for review.
