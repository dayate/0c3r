# Suba Local — panduan jalan di PC sendiri

Versi lokal dari pipeline Colab (`notebook/` → `colab-suba-hardsub-v2.ipynb`).
OCR gratis (RapidOCR/ONNX), blur area subtitle, terjemah gratis dulu + LLM fallback,
hardsub MP4 + SRT.

## Spesifikasi & hasil ukur (PC ini)

| Item | Nilai |
|---|---|
| CPU / RAM | i5-3550 (4c/4t) / 15.9 GB, tanpa GPU NVIDIA |
| ffmpeg | wajib di PATH, butuh `libass` (build gyan/btbn punya) |
| Python | 3.14 (.venv di folder ini) |
| Video uji | 1080x1920, 158 s, 5.5 MB |
| Waktu proses | **~187 s per episode (≈1.2x realtime)** — extract 12 s, OCR 109 s, translate 12 s, render 53 s |
| Output | 22.3 MB (≈4.1x source), libx264 veryfast CRF 23 |

Artinya: 1 episode 2.6 menit ≈ 3 menit proses. 200 episode (±9 jam video) ≈ 11–12 jam nonstop.
Jalankan bertahap (`--limit`) karena script bisa resume.

## Pasang

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
# ffmpeg harus ada di PATH: ffmpeg -version
```

Env: `TIPROUTER_API_KEY` (fallback LLM kalau translator gratis gagal), `DEEPL_API_KEY`
(opsional, gratis pertama kalau ada key). Tanpa key LLM, jalur gratis tetap jalan;
baris yang gagal di semua translator gratis dibiarkan teks Mandarin aslinya.

## Jalan

```powershell
.\.venv\Scripts\python.exe local_pipeline.py                 # semua video di input/
.\.venv\Scripts\python.exe local_pipeline.py --limit 1       # 1 episode (tes)
.\.venv\Scripts\python.exe local_pipeline.py --no-render     # OCR+translate+SRT saja
```

Folder: `input/` (taruh video), `output/per_episode/` (SRT + JSON), `output/hardsub/`
(MP4 per episode), `output/merged/` (gabungan + chapters), `work/` (cache & checkpoint),
`log.txt` (log lengkap tiap run, ditambah tiap run — tidak di-reset).

## Resume

Tiga lapis checkpoint, aman kalau proses dimatikan kapan saja:

1. `work/chunks/<episode>/chunk_NNNNNN.json` — per 600 s. Fingerprint config disimpan;
   kalau `FPS`/`ROI`/`MAX_WIDTH` diubah, chunk otomatis diulang.
2. `output/per_episode/<episode>_ocr.json` — episode selesai OCR+translate tidak diulang.
3. `work/cache/translate_cache.json` — cache terjemahan lintas episode & lintas run.
4. `output/hardsub/*.mp4` yang sudah ada dilewati. Hapus file itu untuk render ulang.

## Knob yang sering dipakai

| Konstanta | Default | Efek |
|---|---|---|
| `FPS` | 1 | 0.5 = OCR 2x lebih cepat, timing subtitle kasar |
| `MAX_WIDTH` | 1080 | 960 lebih cepat tapi baris bisa hilang (diukur) |
| `UPSCALE` | 2 | 1 = cepat, akurasi turun untuk teks kecil |
| `TEXT_GATE` | True | skip frame tanpa teks putih terang (hemat ±70% OCR) |
| `BATCH_SIZE` | 8 | batch deteksi+recognition per panggilan |
| `BLUR_RADIUS` | 12 | blur band subtitle (bukan per-frame) |
| `BLUR_MODE` | "static" | `static` = 1 band; `dynamic` = box per segmen |
| `ALWAYS_BLUR` | True | `True` = band selalu blur (OCR miss tetap tertutup); `False` = time-gate lama |
| `PROGRESS_PCT` | 10 | print progress ffmpeg tiap N persen |
| `CHUNK_SECONDS` | 600 | dari `suba_config.json` (`MAX_CHUNK_DURATION`) |

## Catatan keamanan / fisik

- **NVENC**: dicek otomatis via `nvidia-smi` + daftar encoder ffmpeg. Tanpa GPU
  (seperti PC ini) langsung pakai libx264 — tidak ada fallback diam-diam yang lambat.
  Kalau GPU ada tapi tidak punya NVENC (mis. T4 Colab), pengecekan ini juga menolak.
- **Ukuran output**: hardsub ≈ 4x source karena re-encode + blur. Set `MAX_OUTPUT_MB`
  kalau mau peringatan di log saat melewati batas.
- **Rate limit translator gratis**: `FREE_DELAY = 0.5 s` antar request; Google bisa
  memblokir IP datacenter. Urutan: DeepL (kalau ada key) → Google → MyMemory, sisa
  gagal baru LLM (tiprouter). Jumlah per provider dicetak di log `[tr]`.
- **Batching OCR bukan penghemat besar di CPU**: diukur ~1.0x (CPU sudah 4 core penuh).
  Batching menang di GPU. Penghemat nyata di sini dari sampling 1 fps + gate teks.
- **Blur — dua mode** (`--blur static|dynamic`):
  - `static` (default, CPU): satu band vertikal fixed dari `compute_band()`, di-blur
    sekali lewat `boxblur`, lalu `overlay` ditempel. Dengan `ALWAYS_BLUR=True` (default)
    overlay nyala sepanjang video: subtitle Mandarin yang tidak terdeteksi OCR tetap
    tertutup, dan subtitle ID selalu dibakar di posisi yang sama. `ALWAYS_BLUR=False`
    mengembalikan time-gate `enable='between(t,a,b)+...'` per segmen.
    Biaya encode sama dengan blur always-on (satu overlay).
    Terukur di ep. 1: blur nyala 47 s dari 158 s; frame 95,5 s & 97,5 s identik dengan
    source (mean abs diff 1,5 / 1,0 = noise re-encode), frame 3,5 s beda 24,7 = ter-blur.
  - `dynamic`: satu `split/crop/boxblur/overlay` per segmen, tinggi box dipaksa sama
    dengan band supaya tidak melebar vertikal. Paling presisi, tapi 34 segmen = 34
    overlay (~6,4 KB filtergraph). Untuk GPU/Colab; di CPU jauh lebih lambat.
  - Band dari `compute_band()` membuang bbox outlier (tinggi >1,6x median atau lebar
    <0,4x median), lalu y dipotong p10–p90. Hasil di ep. 1: x 0,184–0,817,
    y 0,643–0,706 (121 px di 1080x1920).
- **Subtitle**: burn pakai ASS sementara (`work/*.ass`) dengan `PlayResX/Y` = ukuran
  video. Ini wajib: `force_style` pada SRT di-scale libass terhadap 384x288 sehingga
  teks jadi raksasa / keluar layar.
