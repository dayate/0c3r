# Suba

Hardsub drama Mandarin ke subtitle Indonesia. OCR teks Mandarin di area subtitle,
terjemahkan, tutup teks aslinya dengan blur, lalu bakar subtitle Indonesia ke video.
Jalan di Colab (GPU) atau PC sendiri (CPU).

## Cara kerja

1. **OCR** — RapidOCR sampling 1 fps di ROI subtitle, checkpoint per 600 detik.
2. **Translate** — gratis dulu (DeepL → Google → MyMemory), sisa gagal baru LLM.
   Cache per baris, jadi baris yang sudah diterjemah tidak diulang.
3. **Blur + Burn** — band blur dihitung dari bbox teks, lalu blur dan subtitle ID
   dibakar dalam satu pass ffmpeg. `ALWAYS_BLUR=True` membuat band selalu blur,
   sehingga teks Mandarin di celah yang tidak terdeteksi OCR tetap tertutup.

Semua tahap resumable: chunk OCR, JSON per episode, cache terjemahan, dan file hardsub
yang sudah ada semuanya dilewati saat run ulang.

## Struktur

```
local_pipeline.py        entry point lokal (CLI)
suba_config.json         durasi chunk + batas episode
notebook/
  build_colab_nb.py      generator notebook Colab
  src/                   sumber tiap cell (config, OCR, translate, render, merge)
tests/                   smoke test render + cell notebook
docs/                    spesifikasi, arsitektur, performa, panduan lokal
input/                   taruh video di sini (tidak di-commit)
output/                  SRT + hardsub + merged (tidak di-commit)
work/                    checkpoint, cache, ASS sementara (tidak di-commit)
```

## Lokal

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
# ffmpeg + ffprobe harus ada di PATH

.\.venv\Scripts\python.exe local_pipeline.py --limit 1     # tes 1 episode
.\.venv\Scripts\python.exe local_pipeline.py               # semua video di input/
```

Env opsional: `TIPROUTER_API_KEY` (fallback LLM), `DEEPL_API_KEY` (translator gratis
pertama). Tanpa keduanya pipeline tetap jalan lewat Google/MyMemory.

Detail parameter, resume, dan angka ukur ada di [docs/GUIDE-LOCAL.md](docs/GUIDE-LOCAL.md).

## Colab

```powershell
python notebook\build_colab_nb.py
```

Buka `notebook/colab-suba-hardsub-v2.ipynb` di Colab, isi cell konfigurasi (path Drive,
API key), lalu jalankan cell 4 (OCR) → 5 (Translate) → 6 (Blur + Burn). Tiap tahap
menampilkan log sendiri dan boleh diulang tanpa mengulang pekerjaan yang sudah selesai.

## Status

- Diukur di PC tanpa GPU (i5-3550, 1080x1920, 158 s): ~187 s per episode, output
  ~4x ukuran source. Render saja 57 s dengan progress per 10%.
- Timing subtitle mengikuti sampling 1 fps, jadi batas akurasi ±1 s. `ALWAYS_BLUR`
  menutup risiko teks Mandarin bocor akibat OCR meleset.
- Translator gratis bisa kena rate limit; baris yang gagal di semua jalur dibiarkan
  teks Mandarin dan tidak di-retry otomatis (hapus `output/per_episode/*_ocr.json`
  untuk mengulang episode itu).
