# Suba

Hardsub drama Mandarin ke subtitle Indonesia. OCR teks Mandarin di area subtitle,
terjemahkan, tutup teks aslinya dengan blur, lalu bakar subtitle Indonesia ke video.
Jalan di Colab (GPU) atau PC sendiri (CPU).

**Scope saat ini (dikunci 2026-11-27): fokus Mandarin dulu.** Bahasa sumber
Mandarin, target Indonesia. Korea / Inggris / Jepang, softsub, dan Whisper-only
ditunda — bukan bagian dari scope ini. **Notebook Colab adalah jalur utama;
pipeline lokal hanya untuk testing**, bukan salinan kedua yang harus dijaga
tetap sama secara manual.

## Cara kerja

1. **OCR** — RapidOCR sampling 1 fps di ROI subtitle, checkpoint per 600 detik.
   Di Colab/Kaggle: RapidOCR 3.x GPU (0,62 dtk/frame, 8,4x vs CPU). Di lokal/PC:
   rapidocr-onnxruntime 1.2.3 CPU. Engine ikut fingerprint di `profiles.yaml`.
2. **Whisper (cell terpisah)** — faster-whisper large-v3-turbo, bahasa Mandarin
   dikunci, untuk merapikan timing OCR dari ±1 detik ke ~0,1–0,2 detik dan
   mengisi baris yang kelewat OCR. Teks tetap dari OCR, timing dari Whisper.
3. **Translate** — CipRouter API: step-3.7-flash dulu, gagal → auto, gagal → daftar review.
   Cache per baris, jadi baris yang sudah diterjemah tidak diulang. **Tidak ada
   baris yang dibiarkan Mandarin di SRT Indonesia** — lihat bagian Translate.
4. **Blur + Burn** — band blur dihitung dari bbox teks, lalu blur dan subtitle ID
   dibakar dalam satu pass ffmpeg. `ALWAYS_BLUR=True` membuat band selalu blur,
   sehingga teks Mandarin di celah yang tidak terdeteksi OCR tetap tertutup.
   Mode blur `static` dan `dynamic` tetap tersedia sebagai opsi.

Semua tahap resumable: chunk OCR, JSON per episode, cache terjemahan, dan file hardsub
yang sudah ada semuanya dilewati saat run ulang.

## Struktur

```
local_pipeline.py        entry point lokal (HANYA UNTUK TESTING, cermin notebook)
suba_config.json         durasi chunk + batas episode
notebook/
  build_colab_nb.py      generator notebook Colab (sumber utama)
  src/                   sumber tiap cell (config, OCR, whisper, translate, render, merge)
tests/                   smoke test render + cell notebook + validator SRT
docs/                    spesifikasi, arsitektur, performa, panduan lokal
input/                   taruh video di sini (tidak di-commit)
output/                  SRT + hardsub + merged (tidak di-commit)
work/                    checkpoint, cache, ASS sementara (tidak di-commit)
```

Sumber kebenaran adalah `notebook/src/`. Kalau ada perbedaan antara notebook
dan `local_pipeline.py`, yang benar adalah notebook.

## Lokal

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
# ffmpeg + ffprobe harus ada di PATH

.\.venv\Scripts\python.exe local_pipeline.py --limit 1     # tes 1 episode
.\.venv\Scripts\python.exe local_pipeline.py               # semua video di input/
.\.venv\Scripts\python.exe local_pipeline.py --profile vm  # profil lain (pc, vm, instabox)
```

Profil per device ada di `profiles.yaml` (colab, kaggle, pc, vm, instabox —
Termux sengaja tidak ada, tidak direkomendasikan). Notebook: pilih PROFILE di
cell config, atau generate varian Kaggle dengan
`python3 notebook/build_colab_nb.py --profile kaggle`.

Env: `TIPROUTER_API_KEY` (wajib untuk translate CipRouter; tanpa ini semua baris
masuk daftar review).

Detail parameter, resume, dan angka ukur ada di [docs/GUIDE-LOCAL.md](docs/GUIDE-LOCAL.md).

## Colab

```powershell
python notebook\build_colab_nb.py
```

Buka `notebook/colab-suba-hardsub-v2.ipynb` di Colab, isi cell konfigurasi (path Drive,
API key), lalu jalankan cell 4 (OCR) → 4b (Whisper timing + fusi) → 5 (Translate) →
6 (Blur + Burn). Cell Whisper boleh dilewati kalau hanya butuh SRT OCR kasar, tapi
timing-nya tetap ±1 detik. Tiap tahap menampilkan log sendiri dan boleh diulang
tanpa mengulang pekerjaan yang sudah selesai.

## Status

- Diukur di PC tanpa GPU (i5-3550, 1080x1920, 158 s): ~187 s per episode, output
  ~4x ukuran source. Render saja 57 s dengan progress per 10%.
- Timing subtitle mengikuti sampling 1 fps, jadi batas akurasi ±1 s. `ALWAYS_BLUR`
  menutup risiko teks Mandarin bocor akibat OCR meleset. **Setelah cell Whisper
  dijalankan, timing dirapikan ke ~0,1–0,2 detik** (teks dari OCR, timing dari
  Whisper) dan baris yang kelewat OCR tapi terdengar di Whisper ditambahkan
  dengan penanda sumber.
- **Baris yang gagal di semua jalur tidak dibiarkan Mandarin** — dicoba step,
  lalu auto (batch + per baris), lalu masuk daftar review
  (`output/per_episode/*_review.json`) kalau masih gagal. SRT Indonesia
  dijamin tidak berisi baris Mandarin yang belum diterjemah; validator SRT
  menolak hasil yang masih berisi baris seperti itu.
- Resume per episode sekarang memeriksa fingerprint konfigurasi (FPS, ROI,
  confidence, upscale, lebar maks, gate). Kalau konfigurasi berubah, episode
  itu diulang, bukan dipakai hasil lamanya.
