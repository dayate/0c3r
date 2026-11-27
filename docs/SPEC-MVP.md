# Spesifikasi MVP Suba — v0.1

> Dokumen ini mengunci ruang lingkup MVP. Berbeda dari PRD §14.1, **Jalur 3 (hardsub/OCR) TIDAK ditunda** dan masuk sebagai bagian MVP.
>
> **Perubahan scope 2026-11-27 (keputusan pengguna): fokus Mandarin dulu,
> notebook-first.** Bahasa sumber hanya Mandarin, target Indonesia. Korea /
> Inggris / Jepang, softsub, dan Whisper-only ditunda. Notebook Colab adalah
> jalur utama; pipeline lokal hanya untuk testing. OCR diimplementasi dengan
> RapidOCR (bukan PaddleOCR seperti tertulis di versi awal dokumen ini).
> Terjemahan: gratis dulu, LLM fallback — bukan LLM utama seperti tertulis
> di D6 versi awal; D6 di bawah sudah dikoreksi.

## 1. Tujuan

Menghasilkan file SRT (bahasa Mandarin dan bahasa Indonesia) dan video hardsub
Indonesia dari video hardsub Mandarin yang diberikan pengguna, melalui notebook
Colab, dengan komputasi di GPU remote (Colab T4).

## 2. Keputusan yang dikunci

| # | Keputusan | Nilai |
|---|---|---|
| D1 | Bentuk produk | Notebook Colab (jalur utama) + pipeline lokal HANYA untuk testing |
| D2 | Runner berat | Google Colab, GPU **T4**, via `colab` CLI v0.8.0 |
| D3 | Bahasa sumber | `zh` saja untuk saat ini (Mandarin dulu) |
| D4 | Bahasa target | `id` |
| D5 | Format output | **SRT saja** (ASS/VTT pasca-MVP) + video hardsub ID |
| D6 | Terjemahan | Gratis dulu (DeepL → Google → MyMemory), LLM fallback; **tidak ada baris Mandarin yang dibiarkan di SRT ID**. Baris MyMemory/Google di-polish LLM (kalau ada key); kartu nama/peran difilter, tanda kutip pembungkus dibersihkan |
| D7 | Jalur pipeline | **Jalur 3 (hardsub/OCR + Whisper timing) saja**; Jalur 1 softsub dan Jalur 2 Whisper-only ditunda |
| D8 | ASR model | Tergantung profil (`profiles.yaml`): GPU (colab/kaggle) `large-v3-turbo` beam 5; CPU (pc/vm/instabox) `small` beam 1 (greedy) — hanya untuk timing/fusi, bukan transkrip utama. Bahasa `zh` dikunci, VAD mati, temperature 0,0, word timestamp nyala |
| D9 | Chunk | 600 detik, idempoten, resumable |
| D10 | Privasi | File sumber hanya untuk pemrosesan; tidak untuk training |
| D11 | Mesin OCR | RapidOCR (bukan PaddleOCR) |
| D12 | Blur | `static` dan `dynamic` tetap tersedia sebagai opsi; default `dynamic` (radius 20, power 3, jendela ±0,4 detik) sejak 2026-11-27 — band statis meninggalkan bayangan glyph di latar gelap dan mengaburkan wajah di area tanpa teks |
| D13 | Profil per device | Satu kode, setting per device di `profiles.yaml` (colab, kaggle, pc, vm, instabox — Termux sengaja tidak ada, tidak direkomendasikan). Notebook: pilih PROFILE di cell config, atau `build_colab_nb.py --profile kaggle` (Colab 24 cell, Kaggle 23 cell). Lokal: `local_pipeline.py --profile pc`. Ganti profil = fingerprint berubah = cache/checkpoint lama tidak dipakai |

## 3. Ruang lingkup MVP

### 3.1 Masuk MVP

- [ ] Cell OCR — Jalur 3 bagian OCR, RapidOCR di T4, ROI subtitle Mandarin
- [ ] Cell Whisper (terpisah) — timing + fusi OCR-Whisper, faster-whisper di T4
- [ ] Cell translate — gratis dulu, LLM fallback berlapis, **jaminan 0 baris Mandarin di SRT ID**, daftar review untuk baris yang masih gagal
- [ ] Cell blur + burn — mode `static` dan `dynamic` sebagai opsi
- [ ] Resume per episode dengan cek fingerprint konfigurasi
- [ ] Validator SRT: timestamp monoton, tidak overlap, ≤2 baris, ≤42 char/baris, durasi 1,0–7,0 detik, 0 baris Mandarin di SRT ID
- [ ] Manifest per job (`job.json`), status per chunk, checksum
- [ ] Glosarium JSON (nama, istilah, honorifik)
- [ ] Export SRT sumber + SRT target + video hardsub ID

### 3.2 Ditunda (pasca-MVP)

- Web UI / desktop app / CLI `suba` (probe, fetch-subs, transcribe, run, resume sebagai perintah CLI)
- Jalur 1 softsub dan Jalur 2 Whisper-only
- Bahasa Korea, Inggris, dan Jepang sebagai sumber
- Format ASS/VTT/plain text
- Konteks multimodal (keyframe ke LLM)
- UI koreksi per segmen dengan keyframe
- Billing, multi-user, retensi otomatis

### 3.3 Bukan bagian produk

- Mengunduh konten terkunci/berbayar
- Menjadi pengganti proofreading manusia untuk rilis publik
- Editor video

## 4. Kontrak antarmuka notebook

Cell dijalankan berurutan, masing-masing resumable dan boleh diulang sendiri:

```
Cell 1 — Mount Drive
Cell 2 — Install (RapidOCR, deep-translator, font)
Cell 3 — Konfigurasi (path Drive, API key, ROI, blur, dsb.)
Cell 4 — OCR (Mandarin, RapidOCR, checkpoint per chunk)
Cell 4b — Whisper timing + fusi (cell terpisah, boleh dilewati)
Cell 5 — Translate (gratis dulu, LLM fallback berlapis)
Cell 6 — Blur + Burn (static / dynamic)
Cell 7 — Merge SRT
Cell 8 — Merge video (opsional)
```

Pipeline lokal (`local_pipeline.py`) hanya cermin untuk testing, bukan antarmuka
utama. Perintah CLI `suba` di versi awal dokumen ini ditunda.

## 5. Alur Jalur 3 (hardsub) — detail MVP

### 5.1 Deteksi hardsub

Indikator (urut dari paling murah):
1. Tidak ada trek subtitle **dan** rasio aspek vertikal (duanju) → curiga hardsub.
2. Sampling 10 frame acak, crop area bawah 25%, jalankan OCR cepat → jika ≥60% frame menghasilkan teks dengan confidence > 0,7 → hardsub terdeteksi.
3. Pengguna dapat override manual (`--pipeline 3`).

### 5.2 Ekstraksi OCR

- Sampling: 1 fps via `ffmpeg -vf fps=1` dengan seek per jendela (bukan decode sekuensial).
- ROI default: (0,05, 0,62, 0,95, 0,93) — area subtitle Mandarin pada video vertikal yang diuji; dapat di-override.
- Preprocessing: grayscale → upscale 2x bila tinggi teks < 20 px → threshold adaptif.
- Inferensi: RapidOCR, deteksi per frame, recognition dibatch.
- Deduplikasi: frame berurutan dengan teks identik digabung jadi satu segmen.
- Output: `chunks/<id>/ocr.json` — `[{start, end, text, conf, bbox}]`

### 5.3 Whisper timing + fusi (cell terpisah, Cell 4b)

Tujuan cell ini hanya satu: **timing yang pas dan tidak miss timing**.
OCR 0.5 fps memberi timing ±2 detik dan bisa melewatkan baris pendek. Whisper
memberi timing kata yang jauh lebih rapat.

- Model: tergantung profil — GPU (colab/kaggle) faster-whisper
  `large-v3-turbo` beam 5; CPU (pc/vm/instabox) `small` beam 1 (greedy),
  bahasa `zh` dikunci. Whisper hanya untuk timing, jadi model kecil sudah
  cukup di CPU — ~4-6x lebih cepat dari large-v3-turbo.
- Setting yang dipakai (metode cepat 2026-11-27): `vad_filter=False`,
  `condition_on_previous_text=False`, `temperature=0.0`, `beam_size`
  sesuai profil (1 CPU / 5 GPU), `word_timestamps=True`.
- OCR + Whisper jalan paralel di pipeline lokal (ThreadPoolExecutor); di
  Colab cell tetap berurutan karena Whisper GPU sudah cepat.
- Audio diekstrak mono 16 kHz, diproses per chunk 600 detik yang sama dengan OCR,
  checkpoint per chunk, resumable. Cell ini boleh dilewati — kalau dilewati,
  timing tetap memakai OCR (±1 detik).
- Aturan fusi (audio dan hardsub sama-sama Mandarin, jadi teks bisa dibandingkan):
  - Teks pakai OCR, timing pakai Whisper. Start/end segmen OCR digeser ke
    word timestamp Whisper yang paling dekat, dengan batas geser wajar.
  - Segmen OCR yang tumpang tindih dengan beberapa segmen Whisper dipecah /
    digabung mengikuti batas Whisper.
  - Baris yang hanya ada di Whisper (OCR kelewat) ditambahkan, ditandai
    `source: "asr"`, dan diterjemahkan seperti baris biasa.
  - Baris yang hanya ada di OCR dipertahankan, ditandai `source: "ocr"`.
  - Kalau teks OCR dan Whisper berbeda jauh pada waktu yang sama, segmen
    ditandai `conflict: true` dan masuk daftar review, teks OCR tetap dipakai.
- Output: `*_ocr.json` diperbarui (segmen terfusi + `source` per segmen),
  plus `*_whisper.json` mentah dan `*_fused.srt` / SRT Mandarin hasil fusi.
  Cell translate membaca hasil fusi ini, bukan hasil OCR mentah.

## 6. Alur terjemahan

- Unit: per adegan = 10–20 baris berurutan (bukan per baris).
- Temperature: 0–0,2.
- Glosarium: diinjeksi ke prompt (pre) **dan** verifikasi pasca (post) — jika nama tidak muncul sesuai glosarium, baris ditandai.
- Mode:
  - `fast` — DeepL untuk semua baris.
  - `balanced` (default) — gratis dulu (DeepL → Google → MyMemory), LLM fallback.
  - `quality` — LLM dengan konteks adegan lebih lebar + instruksi gaya.
- **Jaminan tidak ada baris gagal:** urutan fallback per baris unik adalah
  DeepL → Google → MyMemory → LLM batch (20 baris) → LLM per baris (retry
  2x, jeda backoff) → LLM model kedua. Baris yang masih gagal setelah semua
  itu **tidak** ditulis Mandarin ke SRT ID — baris itu ditulis ke
  `*_review.json` (teks Mandarin + alasan gagal + provider terakhir) dan
  cell translate berhenti dengan status gagal yang jelas, bukan selesai
  diam-diam. Cell translate boleh dijalankan ulang; hanya baris di daftar
  review yang dicoba lagi, baris yang sudah sukses tidak diulang (cache).
- Batas: DeepL request ≤40k karakter per panggilan.
- Panjang baris: maksimum 42 karakter/baris, maksimum 2 baris, durasi tampil 1,0–7,0 detik, CPS ≤17.

## 7. Kriteria penerimaan MVP

| # | Kriteria | Verifikasi |
|---|---|---|
| A1 | Cell OCR pada klip hardsub Mandarin 10 menit selesai di T4, SRT valid | log timer + validator |
| A2 | Cell Whisper pada audio 10 menit menghasilkan SRT dengan RTF ≤0,15 di T4 (warm) | log timer |
| A3 | Cell Whisper + fusi memperbaiki timing OCR: ≥90% segmen bergeser ≤0,5 detik dari timing OCR mentah dan tidak ada segmen yang hilang karena batas chunk | bandingkan SRT sebelum/sesudah fusi |
| A4 | Job yang di-kill di tengah bisa dilanjutkan tanpa mengulang chunk selesai | test resume |
| A5 | SRT valid: timestamp monoton, tidak overlap, ≤2 baris, ≤42 char/baris, durasi 1,0–7,0 detik, **0 baris Mandarin di SRT ID** | validator |
| A6 | Terjemahan ZH→ID lulus skor ≥4,0 pada 3 adegan × 30 segmen | review manual |
| A7 | Nama dari glosarium 100% konsisten di seluruh output | script check |
| A8 | Tidak ada kredensial yang tercetak di log | grep log |
| A9 | Ganti konfigurasi (ROI/FPS) lalu resume: episode lama diulang, bukan dipakai hasil lamanya | test resume + fingerprint |
| A10 | Baris yang gagal di semua jalur translate masuk daftar review dan cell translate berhenti dengan status gagal yang jelas, bukan selesai diam-diam | test fallback |

## 8. Batasan yang diakui

- Akurasi nama diri dan idiom tetap perlu koreksi manusia.
- Jalur 3 tidak akan pernah "instan"; ETA wajib ditampilkan.
- Sesi Colab bisa mati kapan saja → resume adalah fitur inti, bukan tambahan.
- `large-v3-turbo` hanya mendukung transkripsi, bukan task translate bawaan Whisper.
- Whisper di Colab butuh GPU dan download model ~1,6 GB; cell Whisper boleh dilewati, tapi timing kembali ke ±1 detik.
- ROI hardcode untuk video vertikal yang diuji; video dengan posisi subtitle berbeda perlu override ROI manual.

## 9. Pertanyaan terbuka

1. Format ROI: apakah cukup preset untuk MVP, atau perlu editor koordinat?
2. Berapa batas ukuran file yang di-upload ke Colab (500 MB? 2 GB?)?
3. Apakah glosarium di-load otomatis dari file di folder job, atau selalu via flag?
4. Apakah cell Whisper wajib dijalankan, atau tetap opsional setelah diuji di 1–2 episode?
