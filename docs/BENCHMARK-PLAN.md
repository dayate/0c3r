# Rencana Benchmark Suba — Colab T4

## 1. Tujuan

Mengukur performa **end-to-end**, bukan hanya waktu inferensi. Protokol ini memisahkan latency Colab, sinkronisasi file, load model, ASR, OCR, fusi, terjemahan dan render. Hasil menjadi sumber angka untuk target MVP; estimasi eksternal di `PERFORMANCE.md` bukan hasil Suba.

## 2. Benchmark matrix

### ASR / Jalur 2

- Input: 10 menit audio jelas (masing-masing KO, ZH, EN) dengan transcript referensi.
- Model: faster-whisper `large-v3-turbo` di T4; catat versi package, compute type, beam, VAD, language setting.
- Mode: cold session/model; warm model; sequential; batched hanya sebagai eksperimen pembanding.

### Hardsub / Jalur 3

- Input: sekurangnya satu klip 10 menit dengan hardsub, timestamp referensi, ROI diketahui; sertakan kasus audio dan subtitle bahasa sama dan berbeda bila tersedia.
- Ukur OCR 1 fps, ROI, preprocess dan batched sizes 1/8/16; ukur decode/sampling terpisah.
- Ukur ASR paralel vs sekuensial dengan OCR, alignment/fusi, dan terjemahan akhir.
- Tandai video dan ground truth secara lokal dengan checksum; jangan memasukkan materi yang tidak boleh diproses.

### Softsub / Jalur 1

- Input SRT/VTT lokal dan satu URL uji yang dapat diakses.
- Ukur parse/normalisasi SRT lokal terpisah dari fetch URL, agar network/blocking tidak tersamarkan sebagai performa parser.

## 3. Tahap yang diukur

Untuk setiap run catat:

1. Waktu CLI end-to-end (`t_wall_total`).
2. Waktu `colab new` / alokasi + kernel siap.
3. Upload media atau input audio; transfer bytes dan throughput.
4. Cold download model dan load warm terpisah.
5. Probe/extract/decode audio/video.
6. ASR dan OCR terpisah; untuk OCR catat jumlah frame, fps efektif, ukuran batch, ROI.
7. Fusion/alignment, translation per provider, SRT render/validation.
8. Download outputs/checkpoints, peak VRAM (sampling `nvidia-smi`), ukuran artefak.
9. Waktu hingga segmen/chunk pertama selesai.

Semua timer menggunakan monotonic clock; log stage tidak memuat API keys atau teks sensitif secara default.

## 4. Prosedur

1. Pastikan auth CLI berjalan dan `colab sessions` tidak memiliki sisa job benchmark yang membingungkan.
2. Catat commit/code version, `colab version`, package pins, input SHA-256, audio/video metadata, waktu dan konfigurasi runtime.
3. Jalankan cold run (runtime/model cache kosong bila itu dapat dilakukan tanpa menghapus data pengguna), lalu warm run pada sesi/model yang sama.
4. Ulang warm test minimal 3 kali per konfigurasi; laporkan median dan min/max. Jangan menjumlahkan cold start ke model inference.
5. Pada hardsub, validasi OCR hasil terhadap frame/ground truth dan ASR terhadap transcript; waktu cepat dengan output yang hilang/salah tidak lulus.
6. Uji gangguan: hentikan proses setelah satu chunk selesai; jalankan resume dan pastikan chunk done tidak diproses ulang serta checksum tetap sama.
7. Simpan JSON hasil benchmark dan ringkasan Markdown; stop runtime Colab setelah pengukuran.

## 5. Metrik dan rumus

- `RTF_ASR = ASR_seconds / audio_duration_seconds` (lebih kecil lebih cepat).
- `OCR_fps = processed_frames / OCR_stage_seconds`.
- `RTF_job = total_wall_seconds / media_duration_seconds` (mencakup fase yang diputuskan untuk end-to-end; laporkan transfer dan startup terpisah).
- `TTFS = time_of_first_valid_subtitle - job_start`.
- `resume_rework = count(done_chunks_reprocessed)`; target 0.
- Kualitas: WER/CER untuk ASR; character accuracy dan segment recall untuk OCR; human review LLM/DeepL translation. Metrik kualitas tidak dapat diganti dengan throughput.

### Target awal untuk diuji (bukan hasil yang sudah tercapai)

| ID | Skenario | Target awal |
|---|---|---|
| B1 | Softsub lokal, file SRT 15 menit | ≤15 s |
| B2 | ASR warm, 10 menit audio, T4 | RTF ≤0,15 (≤90 s) |
| B3 | Job ASR cold end-to-end 10 menit | ≤4 menit, jika T4 dialokasikan |
| B4 | Hardsub 10 menit, T4, OCR+ASR+fusi | ukur baseline; target dikunci setelah spike |
| B5 | TTF subtitle | ≤60 s setelah media tersedia pada runtime; startup/upload dilaporkan terpisah |
| B6 | Resume | 0 chunk done diulang |
| B7 | VRAM | catat peak; sasaran awal ≤8 GB |

**Catatan:** spesifikasi penerimaan hardsub yang tegas belum ditentukan di sini karena PRD dan riset eksternal belum membuktikan throughput pada video/subtitle Suba. Ukur spike dulu, lalu revisi target dengan bukti. Jangan menyalin target awal menjadi klaim lulus tanpa hasil run.

## 6. Format hasil JSON

```json
{
  "schema_version": 1,
  "run_id": "uuid",
  "timestamp_utc": "...",
  "code_revision": "...",
  "colab_cli_version": "...",
  "runtime": {"gpu_name": "...", "vram_total_mb": null, "vram_peak_mb": null},
  "input": {"sha256": "...", "duration_seconds": 600, "language": "ko", "kind": "audio"},
  "config": {"model": "large-v3-turbo", "compute_type": "float16", "batch_size": 1, "fps": null},
  "stages_seconds": {"allocate": null, "upload": null, "model_download": null, "model_load": null, "decode": null, "asr": null, "ocr": null, "fusion": null, "translate": null, "render": null, "download": null, "wall_total": null},
  "metrics": {"rtf_asr": null, "rtf_job": null, "ttfs_seconds": null, "ocr_fps": null, "wer": null, "cer": null},
  "quality_notes": "",
  "status": "measured|failed"
}
```

## 7. Output dan keputusan setelah benchmark

Simpan hasil asli sebagai `bench/results.jsonl` dan ringkasan dalam `bench/REPORT.md`. Pisahkan fakta terukur, angka dari referensi, dan estimasi. Setelah itu:

- pilih ukuran OCR batch berdasarkan kompromi akurasi/VRAM/throughput;
- putuskan sequential vs batched ASR berdasarkan kualitas KO/ZH/EN;
- tetapkan target hardsub yang realistis;
- konfirmasi operasi resume dari local/durable storage;
- revisi `SPEC-MVP.md`/PRD bila angka tidak memenuhi sasaran.
