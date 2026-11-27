# Arsitektur Suba — MVP

## Status dan batas desain

Dokumen ini menerapkan keputusan MVP terbaru: CLI + Google Colab CLI, Colab T4 sebagai runner GPU default, source `ko`/`zh`/`en`, target `id`, SRT saja, LLM utama + DeepL fallback. **Ketiga jalur, termasuk hardsub/OCR, masuk MVP.**

Logika produk tinggal di paket Python `suba/`; notebook (jika disediakan) hanya menjadi antarmuka opsional, bukan tempat implementasi pipeline. Colab T4 adalah target yang diminta, tetapi ketersediaan GPU bergantung pada akun dan kapasitas Colab. Tidak ada asumsi bahwa T4 selalu dialokasikan.

## 1. Router tiga jalur

| Jalur | Kondisi sumber | Pemrosesan | Artefak inti |
|---|---|---|---|
| **1 — Softsub** | Ada trek/file subtitle teks | Ekstrak, normalisasi, pilih bahasa | SRT sumber |
| **2 — Whisper** | Tidak ada subtitle teks, audio tersedia | Ekstrak audio → faster-whisper | Transkrip bertimestamp + SRT |
| **3 — Hardsub** | Teks subtitle hanya tampak di frame video | OCR frame + ASR audio + alignment/fusi | SRT dari hardsub dan, bila diminta, SRT transkrip audio |

`suba probe` melakukan inspeksi murah terlebih dahulu: media streams, durasi, trek subtitle, codec, dan metadata dasar. Indikasi hardsub bersifat heuristik; pengguna selalu dapat memilih jalur secara manual.

## 2. Pembagian lokal dan Colab

- **Lokal:** CLI, validasi/manifest, deteksi media, pemeriksaan trek, pengambilan softsub URL bila tersedia, dan pengelolaan artefak job.
- **Colab T4:** inferensi Whisper dan OCR yang berat, serta tahapan lain yang memerlukan GPU.
- **Sinkronisasi:** CLI mengirim input yang diperlukan dan menerima hasil/checkpoint per chunk. `/content` Colab dianggap penyimpanan sementara; checkpoint yang dibutuhkan untuk resume harus disalin ke job lokal atau lokasi persisten yang dipilih pengguna.
- **Softsub URL:** coba dari lokal terlebih dahulu untuk menghindari ketergantungan pada IP egress Colab. Ini tidak menjamin berhasil; bila diblokir, sediakan input subtitle lokal atau lanjutkan dengan file sumber yang pengguna miliki.
- Rahasia provider LLM/DeepL tidak boleh ditulis ke manifest/log, notebook output, atau argumen CLI yang dapat terekam. Kirim teks subtitle ke API eksternal hanya dengan konfigurasi provider yang disadari pengguna.

## 3. Jalur 1 — Softsub

1. Periksa trek subtitle file dengan media probe; untuk URL, periksa trek yang tersedia tanpa menganggap platform selalu mengizinkan ekstraksi.
2. Pilih bahasa yang diminta; utamakan subtitle manual jika dapat dibedakan secara andal.
3. Normalisasi timestamp, encoding, markup dan repeated captions menjadi struktur segmen internal.
4. Validasi dan ekspor SRT. Jika bahasa target berbeda, kirim teks ke tahap translate tanpa menjalankan ASR.

Jika fetch URL gagal (bot-check, rate limit, subtitle body kosong), laporkan penyebab yang terdeteksi dan minta file subtitle/video lokal sebagai fallback; jangan mengulang agresif atau menyamarkan kegagalan.

## 4. Jalur 2 — Whisper

1. Ekstrak audio mono 16 kHz.
2. Bagi menjadi chunk sekitar 600 detik; berikan konteks overlap kecil yang dapat dikonfigurasi dan potong hasil pada batas core chunk agar kata di tepi tidak hilang/duplikat.
3. Jalankan faster-whisper `large-v3-turbo` sebagai konfigurasi awal; benchmark kinerja dan kualitas di T4 sebelum memfinalisasi pilihan presisi/parameter.
4. Simpan segmen terstruktur, language, confidence/log probability yang tersedia, durasi setiap tahap, dan checksum.
5. Default untuk kualitas adalah sequential inference. Batching ASR tidak menjadi default sebelum diuji pada KO/ZH/EN karena ada laporan eksternal tentang perbedaan kualitas/segmen hilang.

## 5. Jalur 3 — Hardsub/OCR

### 5.1 Ekstraksi OCR

1. Ambil frame pada interval awal 1 fps, batasi ke ROI; default ROI adalah bagian bawah frame, dapat di-override pengguna.
2. Simpan timestamp frame dan hasil OCR; gunakan teks/frame berurutan untuk mengestimasi rentang tampil subtitle.
3. Coba batched OCR sebagai optimasi, tetapi validasi hasil terhadap mode satu-frame dan data berlabel. Benchmark dokumen OCR tidak dianggap prediksi langsung untuk subtitle.
4. Deduplicate teks berulang yang bersebelahan hanya bila timing dan kemiripan teks mendukung penggabungan.

### 5.2 Bahasa dan alignment/fusi

Bahasa audio dan bahasa hardsub adalah dua parameter terpisah (`audio_lang`, `hardsub_lang`). OCR dapat membaca bahasa yang berbeda dari audio.

- Bila keduanya sama bahasa: gunakan timing ASR sebagai petunjuk alignment; bandingkan teks/confidence hanya pada segmen yang overlap waktunya. Konflik ditandai untuk review, tidak dihapus diam-diam.
- Bila bahasanya berbeda: **jangan membandingkan string OCR dan ASR atau memilih satu berdasarkan kemiripan teks.** OCR menjadi sumber teks hardsub; ASR memberi timing/dialog audio sebagai lapisan terpisah. Hanya hasil OCR yang diterjemahkan untuk menghasilkan subtitle terjemahan hardsub, kecuali pengguna secara eksplisit meminta transkrip audio juga.
- Bila OCR tidak menemukan teks pada interval tertentu, ASR hanya boleh mengisi SRT audio terpisah atau segmen yang disetujui aturan alignment; bukan menggantikan teks hardsub tanpa penandaan.

Ambang confidence, overlap, dan similarity adalah parameter yang perlu dituning dari benchmark berlabel; angka awal dalam SPEC-MVP adalah hipotesis, bukan aturan tervalidasi.

## 6. Terjemahan, render, dan output

1. Susun segmen berurutan ke kelompok kontekstual (awal 10–20 segmen, diputus dengan batas adegan/ukuran request).
2. Kirim ke LLM utama dengan instruksi target Indonesia, konteks dan glossary; validasi jumlah/ID keluaran agar timing tidak bergeser.
3. Jika provider gagal, pakai DeepL fallback sesuai mode dan ketersediaan kredensial; laporkan provider yang menghasilkan teks. Jangan menelan error atau membocorkan secret.
4. Render SRT UTF-8 dengan nomor urut, timestamp valid/monoton, tanpa overlap yang tidak disengaja. SRT adalah satu-satunya format MVP.

## 7. Job dan ketahanan

Setiap job memiliki manifest dan status per chunk. Output chunk hanya ditandai selesai setelah ditulis atomik dan checksum dicatat. Resume memverifikasi checksum input, konfigurasi/model yang relevan, serta artefak output sebelum melewati chunk yang selesai. Artefak persisten di luar VM Colab diperlukan agar resume bertahan dari VM yang dihentikan.

Rincian skema ada di [JOB-CONTRACT.md](JOB-CONTRACT.md).

## 8. Kinerja dan pengukuran

Jangan menganggap estimasi eksternal sebagai jaminan. Catat waktu alokasi/boot Colab, upload, ekstraksi/decode, model cold/warm load, ASR, OCR, terjemahan, validasi SRT, download, serta total wall-clock secara terpisah. Benchmark harus mengukur kualitas dan waktu pada data KO/ZH/EN dan hardsub yang relevan.

Protokol ada di [BENCHMARK-PLAN.md](BENCHMARK-PLAN.md); temuan dan batas klaim ada di [PERFORMANCE.md](PERFORMANCE.md).

---
*Dokumen ini melengkapi PRD root dan SPEC-MVP; keputusan produk aktif ada di [README.md](README.md).*