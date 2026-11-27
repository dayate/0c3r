# Dokumentasi Suba

> **Status:** implementasi sudah ada — hardsub lokal dan notebook Colab, blur band
> always-on, translate gratis dulu + LLM fallback. Lihat [../README.md](../README.md)
> untuk kondisi saat ini. Dokumen di bawah adalah catatan keputusan MVP awal.

Dokumen di folder ini menjabarkan keputusan MVP dan kebutuhan teknis awal. **PRD.md di root tetap sumber konteks produk; dokumen MVP di sini mempersempit dan mengklarifikasi keputusan yang sudah diberikan pengguna.**

## Dokumen

| Dokumen | Tujuan |
|---|---|
| [SPEC-MVP.md](SPEC-MVP.md) | Scope MVP, keputusan produk, alur, acceptance criteria, yang ditunda |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Komponen, alur data, tiga jalur, pemrosesan Colab dan lokal |
| [PERFORMANCE.md](PERFORMANCE.md) | Riset performa, bukti eksternal, batas klaim dan hal yang belum terukur |
| [BENCHMARK-PLAN.md](BENCHMARK-PLAN.md) | Protokol untuk mengukur end-to-end dan menguji target pada T4 |

## Keputusan MVP aktif

- Bentuk: Notebook Colab (jalur utama); pipeline lokal hanya untuk testing.
- Runner default: Colab T4 GPU (ketersediaannya harus dicek saat sesi dibuat).
- Source: Mandarin (`zh`) saja untuk saat ini; target: Indonesia (`id`).
- Output: SRT + video hardsub ID.
- Terjemahan: gratis dulu, LLM fallback berlapis, 0 baris Mandarin di SRT ID.
- Jalur hardsub/OCR + Whisper timing adalah MVP; softsub dan Whisper-only ditunda.
- Job harus bisa disambung ulang setelah sesi Colab atau koneksi terputus, dengan cek fingerprint konfigurasi per episode.

## Status bukti

- PRD berisi pengukuran internal untuk softsub, ASR CPU, hardsub CPU/T4 dan DeepL.
- Sumber luar memberi konteks, bukan jaminan hasil Suba. Perangkat, model/checkpoint, bahasa, decoder, ROI, dan pipeline berbeda dapat mengubah performa.
- Target performa final dikunci setelah protokol di [BENCHMARK-PLAN.md](BENCHMARK-PLAN.md) dijalankan di akun dan lingkungan Colab pengguna.
