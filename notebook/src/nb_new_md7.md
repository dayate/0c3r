## 4–6 — Pipeline (OCR → Whisper → Translate → Blur+Burn)

Empat cell terpisah, jalankan berurutan. Semua tahap resumable:

- **OCR** — checkpoint per chunk (`work/chunks`), hasil per episode `per_episode/*_ocr.json`. Episode yang JSON-nya sudah ada dilewati, **kecuali fingerprint konfigurasi berubah** — kalau berubah, episode diulang.
- **Whisper (cell 4b, terpisah)** — timing + fusi OCR-Whisper, checkpoint per chunk (`work/chunks/*_whisper_chunk_*.json`), hasil mentah `per_episode/*_whisper.json`. Boleh dilewati, tapi timing kembali ke ±1 detik.
- **Translate** — gratis dulu (DeepL → Google → MyMemory), sisa gagal baru LLM berlapis. Cache `work/translate_cache.json`; episode yang semua segmennya sudah diterjemah dilewati. **Tidak ada baris Mandarin yang dibiarkan di SRT ID** — baris gagal masuk `per_episode/*_review.json`.
- **Blur + Burn** — band blur dari bbox OCR, overlay + subtitle ID satu pass ffmpeg. Hardsub yang sudah ada dilewati (hapus file untuk render ulang).
