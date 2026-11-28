# Changelog Suba

Semua perubahan penting proyek ini, terbaru dulu. Tanggal WIB.

## 2026-11-28

- **Batch 20–30 episode per sesi Colab** (pola pakai, bukan kode):
  `MAX_EPISODES` default 200 hanya batas atas; sesi gratis punya batas
  waktu/GPU, jadi bagi job besar jadi beberapa sesi. Checkpoint per
  episode + fingerprint membuat resume aman.
- **Re-scan target di sekitar titik Whisper** (lokal + notebook):
  segmen Whisper-only (suara ada, OCR tidak menemukan teks) di-OCR ulang
  dengan sampling rapat 0,25 dtk (interval ±0,2 dtk) + upscale 4. Segmen
  yang pulih jadi source=`ocr-rescan` (teks dari OCR, timing dari
  Whisper); yang tidak pulih tetap `asr`, tidak ada yang hilang. Kasus
  nyata: 睡了 (2 karakter kecil, ~5,5 dtk) dan 干杯 (transisi 55 dtk)
  lolos dari sampling 0,5 fps. Parameter ikut fingerprint Whisper, jadi
  ganti setting = fusi diulang. Kalau cell OCR belum jalan di sesi
  notebook yang sama, re-scan dilewati dengan pesan.
- **NVENC preset p6 → p5** (lokal + notebook): selangkah lebih lambat dari
  p6, kualitas sedikit lebih baik di T4.
- **Output 720p** (lokal + notebook): video di-scale ke sisi panjang 1280
  (1080x1920 → 720x1280, 1920x1080 → 1280x720) setelah subtitle dibakar —
  proporsi teks tetap. Video yang sudah ≤720p tidak di-scale. Matikan
  dengan `OUTPUT_720P = False`.
- **Name overrides sebelum translate** (lokal + notebook): 温薏 → Wen Yi,
  韩沐宸 → Han Muchen, 闺蜜 → sahabat — diterapkan di dalam fungsi
  translate (`ciprouter_translate` / `llm_translate`) supaya semua jalur
  kena; teks asli (`text_zh`) dan cache tidak diubah.
- **OCR 0,5 fps + Whisper small beam 1** (colab/kaggle, masih tes): ganti
  profil colab/kaggle dari 1 fps + large-v3-turbo beam 5. Perkiraan hemat
  ~60 dtk OCR + ~10-15 dtk Whisper per episode; risiko hilang ~7 baris
  (fusi Whisper menambal timing kasar). Keputusan akhir setelah tes
  episode 1 di Colab (bandingkan jumlah segmen + waktu vs run 1 fps:
  OCR 118,8 dtk, 43 segmen).
- **Blur `none` (V0) jadi default** (lokal + notebook): `build_blur`
  mengembalikan `(None, None)` untuk mode ini dan render langsung
  membakar subtitle tanpa blur. `--blur` lokal sekarang menerima
  `static` / `dynamic` / `none`. Default di `profiles.yaml`,
  `nb_new_config.py`, dan `local_pipeline.py` diganti dari `dynamic` ke
  `none` (profil pc tetap `static`). Alasan: V0 tercepat di T4 (32,3 dtk
  vs static 41,2) dan Taufik menerima trade-off teks Mandarin yang
  bertabrakan dengan sub ID.
- **Terjemahan CipRouter** (D1–D4): Google dihapus dari rantai notebook
  (0/41 dan 0/44 di Colab) dan NLLB dihapus total (D3: kualitas drama
  jelek). Notebook: step-3.7-flash batch 8 dulu, gagal → auto batch 8,
  gagal → auto per baris, gagal → daftar review. Key dari Colab Secrets
  `TIPROUTER_API_KEY` — tidak pernah ditulis di notebook. Benchmark 44
  baris: step 44/44 dalam 31,3 dtk; auto 44/44 dalam 74,1 dtk. Pipeline
  lokal: gratis dulu (DeepL → Google → MyMemory), sisa gagal baru LLM
  TipRouter dengan model yang sama (D4). `deep-translator` dihapus dari
  install notebook (tidak lagi dipakai).
