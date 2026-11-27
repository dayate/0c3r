# Spesifikasi MVP Suba — v0.1

> Dokumen ini mengunci ruang lingkup MVP. Berbeda dari PRD §14.1, **Jalur 3 (hardsub/OCR) TIDAK ditunda** dan masuk sebagai bagian MVP.

## 1. Tujuan

Menghasilkan file SRT (bahasa sumber dan bahasa Indonesia) dari video/audio apa pun yang diberikan pengguna, melalui CLI, dengan komputasi di GPU remote (Colab T4) dan ekstraksi softsub di mesin lokal.

## 2. Keputusan yang dikunci

| # | Keputusan | Nilai |
|---|---|---|
| D1 | Bentuk produk | CLI Python (`suba`) + modul inti yang sama untuk runner Colab |
| D2 | Runner berat | Google Colab, GPU **T4**, via `colab` CLI v0.8.0 |
| D3 | Bahasa sumber | `ko`, `zh`, `en` |
| D4 | Bahasa target | `id` |
| D5 | Format output | **SRT saja** (ASS/VTT pasca-MVP) |
| D6 | Terjemahan | LLM (primary) + DeepL (fallback) |
| D7 | Jalur pipeline | **1, 2, dan 3 semuanya aktif** |
| D8 | ASR model | `large-v3-turbo` (faster-whisper, `compute_type=float16`) |
| D9 | Chunk | 600 detik, idempoten, resumable |
| D10 | Privasi | File sumber hanya untuk pemrosesan; tidak untuk training |

## 3. Ruang lingkup MVP

### 3.1 Masuk MVP

- [ ] `suba probe` — inspeksi sumber (durasi, trek audio, trek subtitle, indikasi hardsub)
- [ ] `suba fetch-subs` — Jalur 1, jalan **lokal** (IP residential), dengan `curl_cffi`
- [ ] `suba transcribe` — Jalur 2, faster-whisper di Colab T4, chunked + resume
- [ ] `suba ocr` — Jalur 3 bagian OCR, PaddleOCR batched di T4
- [ ] `suba fuse` — penggabungan OCR + Whisper jadi SRT sumber
- [ ] `suba translate` — LLM primary, DeepL fallback, glosarium diterapkan
- [ ] `suba run` — orkestrasi end-to-end, memilih jalur otomatis
- [ ] `suba resume` — lanjutkan job dari chunk terakhir
- [ ] Manifest per job (`job.json`), status per chunk, checksum
- [ ] Glosarium JSON (nama, istilah, honorifik)
- [ ] Export SRT sumber + SRT target

### 3.2 Ditunda (pasca-MVP)

- Web UI / desktop app
- Format ASS/VTT/plain text
- Konteks multimodal (keyframe ke LLM)
- UI koreksi per segmen dengan keyframe
- Billing, multi-user, retensi otomatis
- Bahasa Jepang sebagai sumber

### 3.3 Bukan bagian produk

- Mengunduh konten terkunci/berbayar
- Menjadi pengganti proofreading manusia untuk rilis publik
- Editor video

## 4. Kontrak antarmuka CLI

```
suba probe <source>                       # sumber: path file atau URL
suba fetch-subs <source> -l ko --out dir  # Jalur 1, lokal
suba transcribe <job_dir> [--lang ko]     # Jalur 2, via Colab
suba ocr <job_dir> --hardsub-lang en --roi bottom
suba fuse <job_dir>
suba translate <job_dir> --to id [--mode balanced|fast|quality]
suba run <source> --to id [--pipeline auto|1|2|3]
suba resume <job_dir>
```

Exit code: `0` sukses, `1` error tak terpulihkan, `2` butuh intervensi (mis. auth/kuota), `3` sebagian chunk gagal tapi job bisa dilanjutkan.

## 5. Alur Jalur 3 (hardsub) — detail MVP

### 5.1 Deteksi hardsub

Indikator (urut dari paling murah):
1. Tidak ada trek subtitle **dan** rasio aspek vertikal (duanju) → curiga hardsub.
2. Sampling 10 frame acak, crop area bawah 25%, jalankan OCR cepat → jika ≥60% frame menghasilkan teks dengan confidence > 0,7 → hardsub terdeteksi.
3. Pengguna dapat override manual (`--pipeline 3`).

### 5.2 Ekstraksi OCR

- Sampling: 1 fps via `ffmpeg -vf fps=1` dengan seek per jendela (bukan decode sekuensial).
- ROI default: 25% bawah frame; dapat di-override (`--roi bottom|top|full|"x,y,w,h"`).
- Preprocessing: grayscale → upscale 2x bila tinggi teks < 20 px → threshold adaptif.
- Inferensi: PaddleOCR **batched** 8–16 frame per panggilan.
- Deduplikasi: frame berurutan dengan teks identik (Levenshtein < 10%) digabung jadi satu segmen.
- Output: `chunks/<id>/ocr.json` — `[{start, end, text, conf, bbox}]`

### 5.3 Fusi OCR + Whisper

Aturan (dievaluasi per segmen Whisper):

| Kondisi | Aksi |
|---|---|
| OCR conf ≥ 0,85 dan overlap waktu ≥ 50% | Pakai teks OCR, timing dari Whisper |
| OCR conf < 0,85 dan Whisper logprob ≥ -0,5 | Pakai teks Whisper |
| Keduanya tersedia, teks mirip (similarity ≥ 0,8) | Pakai OCR (biasanya lebih akurat untuk hardsub) |
| Keduanya ada tapi berbeda jauh | Tandai `conflict: true`, pakai Whisper, masuk daftar review |
| Hanya salah satu ada | Pakai yang ada, isi `source: "ocr"` atau `"asr"` |

Output: `fused.json` dengan field `source` dan `conflict` per segmen — dipakai untuk laporan kualitas.

### 5.4 Bahasa OCR ≠ bahasa audio

Dua parameter terpisah: `--lang` (audio/ASR) dan `--hardsub-lang` (OCR). Default: `--hardsub-lang` = `--lang`, tapi wajib bisa berbeda (mis. audio Mandarin, hardsub Inggris).

## 6. Alur terjemahan

- Unit: per adegan = 10–20 baris berurutan (bukan per baris).
- Temperature: 0–0,2.
- Glosarium: diinjeksi ke prompt (pre) **dan** verifikasi pasca (post) — jika nama tidak muncul sesuai glosarium, baris ditandai.
- Mode:
  - `fast` — DeepL untuk semua baris.
  - `balanced` (default) — LLM untuk semua, DeepL fallback jika LLM gagal/rate-limited.
  - `quality` — LLM dengan konteks adegan lebih lebar + instruksi gaya.
- Batas: DeepL request ≤40k karakter per panggilan.
- Panjang baris: maksimum 42 karakter/baris, maksimum 2 baris, durasi tampil 1,0–7,0 detik, CPS ≤17.

## 7. Kriteria penerimaan MVP

| # | Kriteria | Verifikasi |
|---|---|---|
| A1 | `suba run` pada video softsub 15 menit menghasilkan SRT valid dalam ≤15 s (lokal) | manual |
| A2 | `suba run` pada audio 10 menit menghasilkan SRT dengan RTF ≤0,15 di T4 | log timer |
| A3 | `suba run` pada klip hardsub 10 menit selesai ≤5 menit di T4 | log timer |
| A4 | Job yang di-kill di tengah bisa dilanjutkan tanpa mengulang chunk selesai | test resume |
| A5 | SRT valid: timestamp monoton, tidak overlap, ≤2 baris, ≤42 char/baris | validator |
| A6 | Terjemahan KO/ZH/EN→ID lulus skor ≥4,0 pada 3 adegan × 30 segmen | review manual |
| A7 | Nama dari glosarium 100% konsisten di seluruh output | script check |
| A8 | Tidak ada kredensial yang tercetak di log | grep log |

## 8. Batasan yang diakui

- Akurasi nama diri dan idiom tetap perlu koreksi manusia.
- Jalur 3 tidak akan pernah "instan"; ETA wajib ditampilkan.
- Sesi Colab bisa mati kapan saja → resume adalah fitur inti, bukan tambahan.
- `large-v3-turbo` hanya mendukung transkripsi, bukan task translate bawaan Whisper.

## 9. Pertanyaan terbuka

1. Format ROI: apakah cukup preset (`bottom`/`top`/`full`) untuk MVP, atau perlu editor koordinat?
2. Apakah `fetch-subs` perlu fallback ke API pihak ketiga bila bot-check menolak?
3. Berapa batas ukuran file yang di-upload ke Colab (500 MB? 2 GB?)?
4. Apakah glosarium di-load otomatis dari file di folder job, atau selalu via flag?
