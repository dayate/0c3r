## 4–6 — Pipeline (OCR → Translate → Blur+Burn)

Tiga cell terpisah, jalankan berurutan. Semua tahap resumable:

- **OCR** — checkpoint per chunk (`work/chunks`), hasil per episode `per_episode/*_ocr.json`. Episode yang JSON-nya sudah ada dilewati.
- **Translate** — gratis dulu (DeepL → Google → MyMemory), sisa gagal baru LLM. Cache `work/translate_cache.json`; episode yang semua segmennya sudah diterjemah dilewati.
- **Blur + Burn** — band blur dari bbox OCR, overlay + subtitle ID satu pass ffmpeg. Hardsub yang sudah ada dilewati (hapus file untuk render ulang).
