# Performa Suba — Temuan Riset & Target

> Status: hasil riset eksternal + baseline internal PRD §5. **Belum ada benchmark Suba sendiri di T4.**
> Semua angka bertanda `[estimasi]` adalah ekstrapolasi, bukan hasil ukur Suba.

## 1. Kesimpulan utama

1. **Kecepatan Whisper bukan risiko utama — sejak profil 2026-11-27, Whisper memakai `small` + beam 1 di profil CPU (pc/vm/instabox) dan `large-v3-turbo` + beam 5 di profil GPU (colab/kaggle), karena hanya untuk timing, bukan transkrip utama.** Model `small` ~4-6x lebih cepat dari `large-v3-turbo` di CPU; risiko sebenarnya ada di *overhead di sekitar model*: alokasi VM Colab, cold download model, upload/download file.
2. **Jalur 3 (hardsub) bukan lagi dibatasi OCR di GPU.** Sejak 2026-11-27, notebook
   Colab/Kaggle pakai RapidOCR 3.x + onnxruntime-gpu (PP-OCRv6): tes 10 frame
   episode 1 di T4 — CPU 5,25 dtk/frame vs GPU **0,62 dtk/frame (8,4x)**,
   teks identik, OCR 5 episode ~7 menit (dulu ~63 menit CPU). Syaratnya CUDA
   runtime cocok dengan build onnxruntime-gpu (Colab CUDA 13 -> ORT >=1.27
   + cuDNN cu13; build lama diam-diam fallback ke CPU — cell OCR men-assert
   CUDA sebelum jalan). Di CPU (pc/vm) OCR tetap 1.2.3 karena 3.x di CPU
   malah lebih lambat (5,25 vs 2,9 dtk/frame).
3. **Jalur 1 (softsub) paling rapuh di lingkungan cloud.** IP datacenter memicu bot-check YouTube; tanpa `curl_cffi` caption body kembali kosong tanpa error.
4. **`BatchedInferencePipeline` memberi ~3x speedup tapi menurunkan kualitas** pada audio tertentu (segmen hilang, bahasa berpindah di tengah segmen).
5. **Kuota Colab tidak bisa dijadikan SLA.** GPU tidak dijamin, VM maksimum 12 jam, tipe akselerator berubah-ubah.

## 2. Bukti eksternal

### 2.1 faster-whisper, 13 menit audio, beam 5 (issue #1030)

| Implementasi | Presisi | Waktu | Peak VRAM | WER (LibriSpeech clean) |
|---|---|---:|---:|---:|
| openai/whisper-large-v3 | fp16 | 2m23s | — | — |
| openai/whisper-turbo | fp16 | 39s | — | — |
| faster-whisper large-v3 | fp16 | 52,0s | 4.521 MB | 2,883 |
| faster-whisper large-v3 | int8 | 52,6s | 2.953 MB | 4,594 |
| faster-whisper large-v3-turbo | fp16 | **19,2s** | 2.537 MB | **1,919** |
| faster-whisper large-v3-turbo | int8 | 19,6s | 1.545 MB | 1,919 |

**Implikasi:** `int8` tidak lebih cepat dari `fp16` di GPU (19,6 vs 19,2 s) meski VRAM separuh. Di T4 (16 GB) pakai `float16`; `int8_float16` hanya jika VRAM mepet.

### 2.2 T4 vs RTX 3070 Ti

Referensi: openai/whisper large-v2 pada file 13 menit = 763 s di T4, 172 s dengan faster-whisper (≈4,4x speedup, ≈4,5x realtime). Turbo ≈2,7x lebih cepat dari large-v3 fp16.

`[estimasi]` T4 + turbo fp16 ≈ **9–12x realtime** → audio 10 menit ≈ 50–70 detik inferensi.

### 2.3 Batched vs sequential

| Mode | Speedup relatif | WER (internal MobiusML) | Risiko |
|---|---:|---:|---|
| `WhisperModel.transcribe` (sequential) | 17,4x | 6,1 | Baseline; konteks antar-30s terjaga |
| `BatchedInferencePipeline` | 86,6x | 6,5 | Segmen hilang, bahasa berpindah, `initial_prompt` bocor (issue #1179) |

**Keputusan:** sequential + `vad_filter=True` sebagai default produksi. Batching hanya untuk pass draf/ETA, dan wajib `language=` dikunci eksplisit.

### 2.4 PaddleOCR, pipeline penuh (det+rec+cls), 960 px sisi panjang

| Model | CPU | T4 |
|---|---:|---:|
| PP-OCRv2 | 330 ms | 111 ms |
| PP-OCR mobile | 356 ms | 116 ms |
| PP-OCR server | 1.056 ms | 200 ms |

**Implikasi:** T4 ≈ 9 fps single-stream (v2). PRD mencatat 1,61 s/frame di CPU — 5x lebih lambat dari benchmark CPU resmi. Selisih itu adalah overhead pipeline (decode frame, crop, loop Python), bukan model.

`[estimasi]` 170 menit @1 fps = 10.200 frame × 111 ms ≈ **19 menit** OCR murni; dengan batching 8 frame bisa lebih rendah lagi.

### 2.5 DeepL

| Batas | Nilai |
|---|---|
| Total request | 128 KiB |
| Header | 16 KiB |
| Dokumen SRT | 150 KB / 500.000 char (free), 1.000.000 char (paid) |
| Billing | Dihitung per Unicode code point |

**Implikasi:** batch per request ≤ ~40k karakter (aman untuk CJK 3 byte/char). Baseline internal: 74k char / ~5 menit ≈ 247 char/s.

### 2.6 Colab

- Free tier: GPU **tidak dijamin**, tipe akselerator berubah-ubah, resource "not guaranteed and not unlimited".
- VM maksimum **12 jam**; sesi bisa berakhir lebih awal karena idle atau demand.
- `colab run` / `colab exec` punya `--timeout` default **30 detik tanpa output** → operasi senyap (download model) akan dianggap gagal.

## 3. Tiga koreksi terhadap asumsi PRD

### 3.1 Bottleneck Jalur 2 = lifecycle sesi, bukan ASR

| Komponen | Estimasi waktu |
|---|---:|
| `colab new --gpu T4` (alokasi + boot) | 60–120 s |
| Cold download model turbo (1,6 GB) | 60–180 s |
| Upload video 20 MB / 500 MB | 10 s / 3–5 menit |
| ASR 10 menit audio | 50–70 s |
| Download SRT | <1 s |

Untuk klip 10 menit, **ASR hanya 20–25% dari wall-clock**. Optimasi ASR lebih jauh tidak akan terasa.

**Konsekuensi:** metrik utama = *time-to-first-subtitle* dan *total wall-clock*, bukan RTF saja.

### 3.2 Bottleneck Jalur 3 = pola akses frame

Optimasi berurutan berdasarkan dampak:
1. Batched OCR inference (8–16 frame per panggilan).
2. Sampling berbasis seek (`ffmpeg -vf fps=1` per jendela) alih-alih decode sekuensial.
3. ROI crop ketat sebelum inferensi.
4. Frame differencing (hanya ~23% menurut PRD — prioritas terakhir).

`[estimasi]` Jalur 3 170 menit: **45–60 menit** di T4, turun dari baseline 2,5 jam.

### 3.3 Jalur 1 harus jalan di IP residential

| Gerbang | Gejala | Perbaikan |
|---|---|---|
| IP egress datacenter | `Sign in to confirm you're not a bot`, HTTP 429 | Proxy residential / cookies / jalankan lokal |
| TLS fingerprint bukan browser | Judul valid, caption body **0 karakter** | Install `curl_cffi` di samping yt-dlp |
| PO Token (2026) | Caption kosong tanpa error | PO token provider |

**Konsekuensi arsitektur:** `probe` + `fetch-subs` dijalankan **lokal**; hasil SRT di-upload ke Colab bila perlu terjemahan/pipeline lanjutan.

## 4. Target performa (menggantikan PRD §12.2)

| ID | Skenario | Target | Cara ukur |
|---|---|---|---|
| P1 | Softsub 15 menit, lokal | ≤15 s wall-clock | `time suba fetch-subs` |
| P2 | ASR 10 menit, T4, warm | RTF ≤0,15 (≤90 s) | log stage timer |
| P3 | ASR 10 menit, T4, cold start | ≤4 menit wall-clock | log stage timer |
| P4 | Hardsub 10 menit, T4 | ≤5 menit (RTF ≤0,5) | log stage timer |
| P5 | Time-to-first-chunk | ≤60 s | timestamp chunk pertama |
| P6 | Resume setelah kill | 0 chunk diulang | bandingkan hash chunk |
| P7 | VRAM puncak | ≤8 GB | sampling `nvidia-smi` |
| P8 | Akurasi | WER ≤0,20 (KO/ZH/EN) pada set uji; nama glossary 100% konsisten | evaluasi manual |

> Ambang P2 sengaja 0,15 — jika regresi ke 0,5 pun masih "lulus" target lama (<1,0), yang membuat target itu tidak berguna sebagai alarm.

## 5. Yang belum terukur (jangan dianggap fakta)

- Kecepatan decode video 170 menit pada 1 fps dengan metode seek vs sequential.
- Akurasi `large-v3-turbo` untuk dialog drama KO/ZH (WER 1,919 di atas adalah LibriSpeech Inggris bersih).
- Kuota Colab aktual untuk akun pengguna.
- Throughput DeepL nyata untuk pasangan KO/ZH→ID pada akun yang dipakai.
- Semua angka `[estimasi]` di dokumen ini.

## 6. Sumber

1. faster-whisper benchmark turbo — issue #1030
2. faster-whisper README (batched, 13 menit → 17 s)
3. MobiusML, "Speeding up Whisper" (VAD batching, 12,5x, WER 6,1→6,5)
4. faster-whisper issue #1179 (regresi kualitas batched)
5. nikolas.blog — T4 vs faster-whisper (763 s → 172 s)
6. nexgpu.net — VRAM & sizing faster-whisper
7. PaddleOCR benchmark (CPU vs T4)
8. DeepL usage limits (128 KiB/request)
9. prepublish.ai — yt-dlp bot check & empty captions
10. Google Colab FAQ (resource tidak dijamin, 12 jam)
11. HuggingFace — whisper-large-v3-turbo (decoder 32→4 layer, transcription-only)
