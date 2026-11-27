# Panduan Test Run di Kaggle (Suba) — Semua Private

Test run notebook Suba di GPU gratis Kaggle (T4 x2), dengan dataset, notebook,
dan output semuanya privat — hanya akunmu yang bisa akses.

**Yang kamu butuhkan**

- Akun Kaggle (gratis, tanpa kartu kredit)
- File `kaggle-suba-hardsub-v2.ipynb` (24 cell, sudah disiapkan, profil `kaggle`)
- 1 episode video untuk tes (mis. `第000001集.mp4`, ~5,7 MB)
- (Opsional) `TIPROUTER_API_KEY` dan `DEEPL_API_KEY` untuk fallback LLM + polish terjemahan

## 0. Sekali saja: verifikasi nomor HP

Kaggle → foto profil → Settings → Phone Verification.

Tanpa ini, GPU dan Internet tidak bisa dinyalakan.

## 1. Buat dataset privat berisi episode

1. Buka kaggle.com → **Datasets** → **New Dataset**.
2. Title: `Duanju Episodes` → slug otomatis jadi `duanju-episodes`.
   Ini penting: notebook mencari episode di `/kaggle/input/duanju-episodes`.
3. Upload `第000001集.mp4` (buat tes, 1 episode dulu).
4. Sharing: pastikan **Private** (ini default di Kaggle, tapi cek sebelum Create).
5. Klik **Create** → tunggu upload + processing selesai.

## 2. Upload notebook

1. Buka kaggle.com/code → **New Notebook**.
2. **File → Import Notebook** → pilih file `kaggle-suba-hardsub-v2.ipynb`.
3. Notebook baru itu privat secara default — jangan klik **Publish** / **Share**.

## 3. Atur setting notebook (panel kanan)

- **Accelerator: GPU T4 x2**
- **Internet: On** (wajib: download model Whisper dari HuggingFace + API translate)
- **Persistence: Files only** (default — supaya `/kaggle/working` dan checkpoint
  tetap ada kalau sesi di-restart)
- **Add Data → Your Datasets** → pilih `duanju-episodes`.
  Ini yang me-mount dataset ke `/kaggle/input/duanju-episodes`.
  Lakukan sebelum Run All; kalau sesi sudah jalan, restart session dulu.
- **Add-ons → Secrets** → tambah `TIPROUTER_API_KEY` (dan `DEEPL_API_KEY`
  kalau ada). Jangan pernah tempel key di dalam cell mana pun.

## 4. Sesuaikan config (cell 3 — Konfigurasi Utama)

- `PROFILE` sudah `"kaggle"` (dari generator).
- `MAX_EPISODES = 1` (tes 1 episode dulu; default-nya 200).
- Cek `EPISODES_DIR` = `/kaggle/input/duanju-episodes`. Kalau slug
  dataset-mu beda, samakan di sini.
- Nilai OCR sudah pakai hasil tuning episode 1 (ROI 0.05/0.55/0.95/0.93,
  min_conf 0.55, upscale 3) — cell tuning 3c boleh dilewati.

## 5. Jalankan

Run All, atau jalankan cell berurutan:

1 (info) → 2 (install) → 3 (config) → 3b (validator) → 4 (OCR) →
4b (Whisper) → 5 (translate) → 6 (render) → 7 (merge SRT) →
8 (merge video, opsional)

- Estimasi episode 1 (~158 detik): **~3–6 menit** di T4 x2.
- Cell 4b (Whisper) boleh dilewati kalau mau lebih cepat, tapi timing
  jadi kurang akurat.
- Batasan Kaggle gratis: sesi maks 12 jam, idle ~20–40 menit bisa
  ke-putus, kuota GPU 30 jam/minggu, output maks ~20 GB.

## 6. Unduh hasil

- Tab **Output** di halaman notebook → unduh filenya:
  `*_id.srt` (subtitle Indonesia), `*_zh.srt`, `*_id_hardsub.mp4` (video),
  folder `merged/`.
- Atau via Kaggle CLI:
  `kaggle kernels output <username>/<notebook-slug> -p ./hasil/`
- Output ada di `/kaggle/working/suba_hardsub/` selama sesi berjalan.

## 7. Bersih-bersih (privasi)

Setelah hasil diunduh, kalau tidak mau ada salinannya di Kaggle:

- Hapus dataset (halaman dataset → Settings → Delete).
- Hapus notebook (menu ⋮ di halaman notebook → Delete).
- Jangan klik **Publish** di notebook atau dataset — itu yang membuatnya publik.

## Checklist privasi (sebelum Run All)

- [ ] Dataset: **Private** (bukan Public)
- [ ] Notebook: belum di-publish, tidak ada collaborator
- [ ] API key hanya di **Secrets**, tidak ada di cell mana pun
- [ ] Tidak ada link/tunnel yang dibagikan (notebook ini tidak membuka tunnel apa pun)

## Catatan jujur soal privasi

"Private" di Kaggle artinya hanya akunmu (dan orang yang kamu undang
sebagai collaborator) yang bisa melihat dataset, notebook, dan output.
File-nya tetap tersimpan di server Kaggle — bukan zero-knowledge. Kalau
mau 100% tidak keluar dari mesin sendiri, jalankan di PC lokal
(`local_pipeline.py --profile pc`).

## Troubleshooting singkat

- `FileNotFoundError: /kaggle/input/duanju-episodes` → dataset belum
  di-attach (Add Data) atau slug beda → samakan `EPISODES_DIR`.
- Whisper gagal download model → Internet belum On.
- Translate gagal semua → cek Secrets terpasang; tanpa key pun translator
  gratis tetap dicoba dulu (DeepL → Google → MyMemory → LLM).
- Sesi mati di tengah → resume: checkpoint OCR/Whisper per chunk tersimpan
  di `/kaggle/working` (selama Persistence: Files only), jalankan ulang
  cell yang sama — fingerprint cocok = pakai checkpoint lama.
- Error `libcublas` → seharusnya tidak terjadi di Kaggle (library CUDA
  sudah ada di image); kalau muncul, kabari.
