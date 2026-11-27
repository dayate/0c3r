# Suba Hardsub Mandarin -> Indonesia (Colab GPU)

Versi notebook dari pipeline lokal (`local_pipeline.py`). Pipeline dipisah tiga tahap
yang bisa dijalankan ulang sendiri-sendiri:

1. **OCR** — RapidOCR (gratis) sampling `FPS=1` di ROI subtitle, checkpoint per chunk.
2. **Translate** — gratis dulu (DeepL → Google → MyMemory), sisa gagal baru LLM
   tiprouter. Cache per baris, jadi baris yang sudah diterjemah tidak diulang.
3. **Blur + Burn** — band blur dihitung dari bbox teks, lalu blur + subtitle ID
   dibakar dalam satu pass ffmpeg.

Catatan blur:

- `ALWAYS_BLUR=True` (default) membuat band selalu blur sepanjang video. Ini yang
  menutup kasus OCR miss — subtitle Mandarin di celah yang tidak terdeteksi tetap
  tertutup, dan subtitle Indonesia selalu dibakar di posisi band yang sama.
- `ALWAYS_BLUR=False` kembali ke perilaku time-gate (`enable='between(t,a,b)+...'`):
  blur hanya nyala saat ada segmen terdeteksi.
- `BLUR_MODE="dynamic"` = box per segmen (tinggi dikunci ke band), paling rapat tapi
  N× crop+blur+overlay — butuh GPU.

Subtitle burn pakai ASS dengan `PlayResX/Y` = ukuran video (bukan `force_style` di SRT,
yang di-scale libass terhadap 384x288 sehingga teks jadi raksasa).

**Isi dulu cell "3 — Konfigurasi"** (path Drive + API key), lalu jalankan cell 4, 5, 6 berurutan.
