# Suba Hardsub Mandarin -> Indonesia (Colab GPU)

Versi notebook dari pipeline lokal (`local_pipeline.py`). Pipeline dipisah tiga tahap
yang bisa dijalankan ulang sendiri-sendiri:

1. **OCR** — RapidOCR (gratis) sampling `FPS=1` di ROI subtitle, checkpoint per chunk.
2. **Whisper (cell terpisah)** — faster-whisper large-v3-turbo, bahasa Mandarin dikunci, merapikan timing OCR dari ±1 detik ke ~0,1–0,2 detik dan mengisi baris yang kelewat OCR.
3. **Translate** — CipRouter API: step-3.7-flash dulu, gagal → auto, gagal → daftar review. Cache per baris, jadi baris yang sudah diterjemah tidak diulang. **Tidak ada baris Mandarin yang dibiarkan di SRT Indonesia.**
4. **Blur + Burn** — band blur dihitung dari bbox teks, lalu blur + subtitle ID dibakar dalam satu pass ffmpeg.

Catatan blur (default `BLUR_MODE="none"` / V0 sejak 2026-11-28):

- `BLUR_MODE="none"` = tanpa blur — subtitle ID dibakar apa adanya, paling cepat.
- `ALWAYS_BLUR=True` (default) membuat band selalu blur sepanjang video. Ini yang
  menutup kasus OCR miss — subtitle Mandarin di celah yang tidak terdeteksi tetap
  tertutup, dan subtitle Indonesia selalu dibakar di posisi band yang sama.
- `ALWAYS_BLUR=False` kembali ke perilaku time-gate (`enable='between(t,a,b)+...'`):
  blur hanya nyala saat ada segmen terdeteksi.
- `BLUR_MODE="dynamic"` = box per segmen (tinggi dikunci ke band), paling rapat tapi
  N× crop+blur+overlay — butuh GPU.

Subtitle burn pakai ASS dengan `PlayResX/Y` = ukuran video (bukan `force_style` di SRT,
yang di-scale libass terhadap 384x288 sehingga teks jadi raksasa).

**Isi dulu cell "3 — Konfigurasi"** (path Drive + API key), lalu jalankan cell 4, 4b, 5, 6 berurutan.
