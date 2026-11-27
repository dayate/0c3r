# PRD — Suba: Universal AutoTranscribe & AutoSubtitle

**Nama produk:** Suba (nama kerja, dapat diganti)
**Jenis dokumen:** Product Requirements Document (PRD) teknis
**Versi:** 0.1 — Draft berdasarkan riset dan uji coba
**Tanggal:** 26 November 2026
**Status:** Belum dibangun — dokumen perencanaan sebelum pengembangan

---

## 1. Ringkasan eksekutif

Suba adalah tool untuk membuat transkrip dan subtitle secara otomatis dari video atau audio apa pun, untuk berbagai bahasa dan berbagai jenis konten. Tool ini tidak terbatas pada fansub drama China vertikal (duanju / micro drama), dan tidak terbatas pada bahasa Mandarin. Bahasa yang menjadi target awal adalah Mandarin, Korea, Jepang, Inggris, dan Indonesia sebagai bahasa hasil terjemahan, dengan desain yang memungkinkan penambahan bahasa lain tanpa membangun ulang sistem.

Kesimpulan utama dari riset dan uji coba yang sudah dilakukan adalah: tool ini layak dibangun, tetapi performa adalah syarat utamanya. Sebuah tool hanya berguna jika prosesnya terasa lebih mudah dan lebih cepat daripada cara manual. Cara manual untuk membuat subtitle umumnya membutuhkan waktu 5–10 kali durasi video. Jika tool otomatis justru membutuhkan waktu di atas 1 kali durasi video pada jalur yang paling sering dipakai, tool tersebut gagal memenuhi tujuan dasarnya.

Karena itu, Suba dirancang dengan prinsip **routing tiga jalur**: tidak semua video diperlakukan sama. Video yang sudah memiliki subtitle tertanam lunak (softsub) diproses dalam hitungan detik. Video tanpa subtitle diproses dengan pengenalan suara (speech recognition). Hanya video dengan subtitle yang menempel permanen di gambar (hardsub) yang diproses dengan jalur terberat, yaitu OCR ditambah pengenalan suara. Keputusan jalur ini, ditambah penggunaan GPU atau API cloud untuk komputasi berat, adalah fondasi performa Suba.

Dokumen ini merangkum tujuan produk, rancangan pipeline, bukti angka dari uji coba nyata, persyaratan fungsional, strategi terjemahan, seluruh masalah yang sudah diketahui, solusi yang disarankan, dan roadmap pengembangan bertahap.

## 2. Latar belakang

### 2.1 Titik awal: fansub drama vertikal

Riset dimulai dari kebutuhan spesifik: menonton dan mengunduh episode drama vertikal China (Hongguo duanju) tanpa episode terkunci, lalu menambahkan subtitle Indonesia ke video yang subtitle Mandarin-nya sudah menempel permanen di gambar (hardsub). Untuk kasus itu dikembangkan metode fusi dua sumber:

- **OCR (Optical Character Recognition)** membaca teks hardsub yang terlihat di frame video. Sumber ini kuat untuk isi teks, tetapi lemah untuk bahasa dan model tertentu.
- **Whisper** mendengarkan audio dan menghasilkan transkrip dengan penanda waktu (timestamp). Sumber ini kuat untuk timing, tetapi dapat salah dengar.

Hasil keduanya digabungkan, lalu diterjemahkan. Metode ini terbukti bekerja, tetapi juga terbukti paling lambat dari semua jalur yang diuji.

### 2.2 Generalisasi: dari satu kasus ke tool umum

Dari riset tersebut muncul kesimpulan yang lebih luas: komponen yang sama — ekstraksi subtitle, pengenalan suara, OCR, dan terjemahan — sebenarnya berlaku untuk hampir semua jenis video dan konten, misalnya:

- Video YouTube: wawancara, vlog, live streaming, podcast video
- Drama dan film: drama China, drama Korea, drama Jepang, serial berbahasa Inggris
- Konten edukasi: kuliah, tutorial, webinar, presentasi
- Konten kerja: rekaman meeting, wawancara riset, dokumentasi
- Arsip pribadi: video keluarga, rekaman suara, catatan video

Perbedaannya bukan pada tujuan akhirnya — semuanya berakhir pada file subtitle seperti SRT — melainkan pada kondisi sumbernya. Sebagian video sudah punya softsub, sebagian hanya punya audio yang jelas, dan sebagian hanya bisa dibaca lewat hardsub. Tool umum harus mengenali kondisi itu secara otomatis, bukan memaksa satu metode untuk semua video.

### 2.3 Masalah yang diselesaikan

- Membuat subtitle secara manual lambat, melelahkan, dan sulit konsisten untuk video panjang.
- Tool yang ada umumnya mengunci pengguna pada satu bahasa, satu jenis video, atau satu metode saja.
- Hasil transkripsi mentah sering tidak siap pakai: nama tokoh tidak konsisten, kesalahan dengar terbawa ke terjemahan, dan baris subtitle terlalu panjang untuk dibaca.
- Pengguna non-teknis terhalang oleh alur kerja teknis, misalnya notebook dengan banyak sel yang harus disalin dan dijalankan manual satu per satu.

## 3. Tujuan dan non-tujuan

### 3.1 Tujuan produk

- Menghasilkan transkrip dan subtitle yang dapat diunduh (minimal format SRT) dari URL video atau file unggahan, dengan intervensi manual seminimal mungkin.
- Mendukung banyak bahasa sumber dan bahasa target tanpa perubahan arsitektur.
- Menyelesaikan video 10 menit dalam waktu di bawah durasi videonya pada jalur Whisper di GPU, dan dalam hitungan detik pada jalur softsub.
- Memberikan hasil per bagian (per chunk) secara bertahap, sehingga pengguna tidak harus menunggu seluruh video selesai untuk mulai memeriksa hasil.
- Menjaga konsistensi nama tokoh dan istilah melalui glosarium (glossary) yang dapat diisi pengguna atau dibuat otomatis lalu dikoreksi.
- Membuat proses dapat dilanjutkan (resume) jika terputus, tanpa mengulang bagian yang sudah selesai.

### 3.2 Non-tujuan untuk versi awal

- Bukan editor video lengkap. Pengeditan kreatif, pewarnaan, dan efek di luar cakupan.
- Bukan pengganti proofreading manusia untuk rilis publik. Hasil otomatis adalah draf berkualitas tinggi yang tetap perlu diperiksa, terutama untuk nama orang, nama tempat, dan idiom.
- Tidak menjanjikan jalur OCR berjalan cepat di CPU lokal. Jalur hardsub membutuhkan GPU atau API, dan batasan ini harus ditampilkan secara jujur di antarmuka.
- Tidak berfokus pada unduhan video dari platform yang melarangnya, dan tidak menangani pengunduhan episode terkunci sebagai fitur produk. Suba memproses video atau audio yang diberikan pengguna.
- Tidak melakukan terjemahan dengan satu model untuk semua bahasa. Strategi terjemahan dirancang per pasangan bahasa, seperti dijelaskan di Bagian 9.

### 3.3 Pengguna target

- **Pembuat fansub dan penerjemah komunitas** yang mengerjakan drama dan konten asing secara rutin.
- **Kreator dan penonton konten multibahasa** yang membutuhkan subtitle Indonesia atau bahasa lain untuk video YouTube, live, dan podcast.
- **Pengguna umum non-teknis** yang hanya ingin mengunggah file, memilih bahasa, dan mengunduh SRT.
- **Pengguna teknis / power user** yang ingin mengatur model, bahasa OCR, area baca (region of interest), dan glosarium secara manual.

Prinsip desain untuk semua segmen: alur utama harus sesederhana "berikan video, pilih bahasa, unduh subtitle". Pengaturan lanjutan tersedia, tetapi tidak menghalangi alur utama.

## 4. Tiga jalur pipeline

Inti arsitektur Suba adalah router yang memeriksa sumber, lalu memilih jalur termurah yang masih menghasilkan kualitas yang dibutuhkan.

| Jalur | Kondisi sumber | Metode utama | Kecepatan relatif |
|---|---|---|---|
| 1 — Softsub | Subtitle sudah tersedia sebagai trek teks | Ekstraksi langsung | Instan, hitungan detik |
| 2 — Whisper | Tidak ada subtitle, audio tersedia | Speech recognition saja | Menengah, target di bawah 1x durasi di GPU |
| 3 — Hardsub | Subtitle menempel permanen di gambar | OCR + Whisper, lalu fusi | Paling lambat, butuh GPU/API |

### 4.1 Jalur 1 — Ekstraksi softsub

Jika sumber adalah URL YouTube atau file dengan trek subtitle, Suba mengambil trek subtitle yang sudah ada, mengutamakan subtitle manual daripada subtitle hasil generasi otomatis (auto-generated), lalu menormalkannya menjadi SRT. Jalur ini tidak menjalankan Whisper maupun OCR sama sekali.

Detail yang harus ditangani:

- Memilih bahasa trek yang diminta pengguna jika tersedia lebih dari satu bahasa.
- Membersihkan format bawaan platform (misalnya tag dan pengulangan baris pada subtitle otomatis) menjadi segmen SRT yang bersih.
- Jika pengguna meminta bahasa lain, hasil ekstraksi diteruskan ke tahap terjemahan, bukan ke tahap transkripsi ulang.

### 4.2 Jalur 2 — Whisper saja

Jika tidak ada softsub, Suba mengekstrak audio, menormalkannya (acuan uji coba: mono 16 kHz), lalu menjalankan model Whisper, misalnya melalui implementasi faster-whisper. Jalur ini adalah jalur utama untuk mayoritas video umum: YouTube tanpa subtitle, podcast, meeting, vlog, dan live.

Detail yang harus ditangani:

- Deteksi bahasa audio otomatis, dengan opsi pengguna mengunci bahasa sumber agar deteksi tidak meleset.
- Pembagian audio menjadi chunk (acuan: sekitar 10 menit) agar dapat diproses paralel dan dilanjutkan jika gagal.
- Model bertingkat: model kecil untuk draf dan timing awal, model besar (misalnya large-v3-turbo) untuk hasil final atau untuk baris dengan kepercayaan rendah.

### 4.3 Jalur 3 — OCR + Whisper untuk hardsub

Jika subtitle menempel di gambar dan tidak ada trek teks, Suba menjalankan dua proses sekaligus, lalu menggabungkan hasilnya:

- **OCR** mengambil frame pada interval tertentu (acuan awal: 1 frame per detik), memotong hanya area subtitle (region of interest / ROI), dan membaca teks hardsub. Bahasa OCR mengikuti bahasa hardsub, bukan bahasa audio — keduanya bisa berbeda, misalnya hardsub Inggris dengan audio Mandarin.
- **Whisper** mentranskripsikan audio seperti pada Jalur 2, sebagai sumber timing utama dan cadangan isi.
- **Fusi** menyelaraskan hasil OCR dan Whisper berdasarkan timestamp, memilih teks yang lebih dapat dipercaya per segmen, dan menghasilkan SRT dalam bahasa sumber, yang kemudian dapat diterjemahkan.

Jalur ini adalah satu-satunya jalur yang menjalankan OCR. Menjadikan OCR sebagai jalur bawaan untuk semua video adalah kesalahan desain yang harus dihindari, karena jalur ini menahan performa seluruh produk pada kasus terberatnya.

## 5. Bukti uji coba dan benchmark terukur

Angka di bagian ini adalah hasil pengukuran nyata selama riset, bukan estimasi. Angka ini menjadi garis dasar (baseline) untuk target performa di Bagian 12. Lingkungan CPU yang dimaksud adalah mesin virtual / PC kelas lama tanpa GPU khusus (acuan perangkat: prosesor Intel Core i5-3550). Lingkungan GPU yang dimaksud adalah Google Colab dengan GPU T4.

### 5.1 Uji Jalur 1 — Softsub YouTube

Sumber uji: video YouTube berdurasi sekitar 910 detik (sekitar 15 menit 10 detik), berupa wawancara berbahasa Korea dengan subtitle manual dalam tiga bahasa.

- Subtitle manual tersedia dalam bahasa Korea (468 segmen), Inggris (472 segmen), dan Indonesia (468 segmen).
- Pengambilan berhasil melalui library transcript khusus dalam hitungan detik untuk seluruh video.
- Hambatan yang ditemui: klien pengunduh standar terkena pemeriksaan bot (bot-check) YouTube, dan percobaan pengambilan salah satu bahasa sempat terkena pembatasan permintaan (RequestBlocked) dan baru berhasil setelah jeda sekitar 20 detik sebelum mencoba lagi.

Kesimpulan: jalur softsub terbukti instan dan harus selalu dicoba pertama kali.

### 5.2 Uji Jalur 2 — Whisper untuk file tanpa softsub

Sumber uji: file video vertikal berdurasi 85,1 detik, resolusi 1080x1440, ukuran sekitar 20 MB, hanya berisi trek video dan audio tanpa trek subtitle. Isi berupa siaran langsung (live) berbahasa Korea.

Hasil dengan faster-whisper model large-v3-turbo di CPU:

| Tahap | Waktu terukur |
|---|---:|
| Pemuatan model (model load) | 16,3 detik |
| Transkripsi (transcribe) | 110,3 detik |
| Total untuk audio 85 detik | 126,6 detik |

Artinya, di CPU, jalur ini membutuhkan sekitar 1,5 kali durasi audio. Deteksi bahasa bekerja sempurna (Korea, probabilitas 1,00) dan dihasilkan 22 segmen yang secara umum dapat dibaca dengan benar. Namun terdapat kesalahan dengar yang nyata, dibahas di Bagian 11.

Sebagai pembanding internal, kecepatan Whisper di CPU pada pekerjaan sebelumnya terukur sekitar 0,81 kali realtime.

### 5.3 Uji Jalur 3 — OCR + Whisper untuk hardsub durasi panjang

Sumber uji: video hardsub berdurasi sekitar 170 menit, hardsub Inggris dengan audio Mandarin.

| Lingkungan | Pengaturan | Waktu total terukur |
|---|---|---:|
| CPU saja | OCR sekitar 1,61 detik per frame, 1 fps | Sekitar 8,5 jam |
| CPU saja | 2 fps | Sekitar 13 jam |
| Colab GPU T4 | Pipeline penuh | Sekitar 2,5 jam (sekitar 0,88x durasi) |

Kesimpulan: perpindahan dari CPU ke GPU mengubah jalur ini dari "tidak praktis" menjadi "dapat dipakai", tetapi tetap belum terasa instan. Karena itu jalur ini harus diberi estimasi waktu (ETA) yang jelas di antarmuka, dan tidak boleh menjadi jalur bawaan.

### 5.4 Uji terjemahan massal

Terjemahan massal dengan mesin terjemahan khusus (DeepL) pada pekerjaan sebelumnya terukur memproses sekitar 74 ribu karakter dalam sekitar 5 menit tanpa kegagalan. Angka ini menjadi acuan bahwa terjemahan massal sebaiknya tidak seluruhnya dikerjakan oleh model bahasa besar (LLM) yang lebih lambat dan lebih mahal, melainkan dikombinasikan seperti dijelaskan di Bagian 9.

### 5.5 Uji penghematan frame yang ternyata kecil

Teknik melewatkan frame yang tidak berubah (frame differencing) pernah diasumsikan dapat menghemat 70–80% waktu OCR. Pengukuran nyata pada video uji kedua hanya menghemat sekitar 23%, karena latar belakang video bergerak. Teknik ini tetap berguna, tetapi tidak boleh dijadikan tumpuan utama rencana performa.

## 6. Alur pengguna

### 6.1 Alur utama

1. Pengguna memberikan sumber: menempelkan URL (misalnya YouTube) atau mengunggah file video/audio.
2. Suba memeriksa sumber secara otomatis: durasi, trek audio, trek subtitle yang tersedia, dan perkiraan ada atau tidaknya hardsub.
3. Suba menampilkan jalur yang akan dipakai (Softsub / Whisper / Hardsub), bahasa sumber yang terdeteksi, dan perkiraan waktu selesai. Pengguna dapat mengubah bahasa sumber, bahasa hardsub, dan bahasa target sebelum mulai.
4. Pengguna menekan tombol mulai. Tidak ada langkah teknis tambahan yang wajib.
5. Pemrosesan berjalan per chunk. Hasil setiap chunk langsung dapat dilihat dan diunduh sebagian, lengkap dengan bilah kemajuan dan ETA.
6. Pengguna mengunduh hasil akhir: SRT bahasa sumber, SRT bahasa target, atau keduanya. Jika terjemahan diminta, pengguna memilihnya di langkah 3, bukan sebagai proses terpisah yang membingungkan.

### 6.2 Alur koreksi

1. Pengguna membuka pratinjau subtitle per segmen, idealnya berdampingan dengan video atau keyframe untuk segmen tersebut.
2. Pengguna mengoreksi teks sumber yang salah sebelum diterjemahkan ulang, karena kesalahan sumber akan terbawa ke semua bahasa target.
3. Pengguna mengisi atau mengoreksi glosarium nama tokoh dan istilah, lalu menerapkan ulang terjemahan hanya pada baris yang terpengaruh.
4. Pengguna mengekspor ulang SRT tanpa memproses ulang audio atau video.

### 6.3 Alur jika proses terputus

Jika koneksi, sesi, atau worker terputus, pekerjaan harus dapat dilanjutkan dari chunk terakhir yang selesai. Pengguna tidak boleh diminta mengunggah ulang atau memulai dari nol untuk pekerjaan yang sebagian sudah selesai, selama file sumber dan hasil chunk masih tersimpan.

## 7. Persyaratan fungsional

### 7.1 Masukan dan pemeriksaan sumber

- Menerima URL video dan unggahan file video/audio dengan batas ukuran dan durasi yang ditampilkan secara eksplisit.
- Mendeteksi trek subtitle, bahasa trek, dan membedakan subtitle manual dari subtitle otomatis.
- Mendeteksi bahasa audio secara otomatis dan mengizinkan penguncian bahasa secara manual.
- Untuk jalur hardsub, mengizinkan pengguna menentukan bahasa hardsub dan area baca (ROI) jika deteksi otomatis meleset.
- Menampilkan peringatan sebelum memulai jalur berat: perkiraan waktu, kebutuhan GPU/API, dan perkiraan biaya jika memakai API berbayar.

### 7.2 Pemrosesan

- Router otomatis memilih Jalur 1, 2, atau 3, dan pengguna dapat menimpanya (override) dengan alasan yang tercatat.
- Pemrosesan per chunk dengan status per chunk: menunggu, berjalan, selesai, gagal, dapat dicoba lagi.
- Penyimpanan hasil antara (intermediate) per chunk: audio bersih, hasil Whisper, hasil OCR, hasil fusi, dan hasil terjemahan.
- Model tidak diunduh ulang jika sudah ada di cache. Pemeriksaan cache dilakukan sebelum pekerjaan dimulai.
- Frame untuk OCR diproses di memori atau penyimpanan sementara yang efisien, bukan disimpan sebagai ribuan file gambar permanen tanpa kebutuhan.

### 7.3 Keluaran

- Ekspor SRT bahasa sumber dan satu atau lebih bahasa target dalam satu pekerjaan.
- Opsi ekspor tambahan yang direncanakan: VTT dan teks transkrip biasa (plain text) dengan dan tanpa timestamp.
- Setiap baris subtitle mematuhi batas keterbacaan yang dapat diatur: jumlah karakter per baris dan durasi tampil minimum/maksimum.
- Unduhan parsial per chunk dan unduhan final yang sudah digabungkan.

### 7.4 Terjemahan dan glosarium

- Glosarium per proyek: nama tokoh, nama tempat, istilah khusus, dan bentuk sapaan yang harus konsisten.
- Terjemahan dikirim per adegan atau per kelompok baris yang berurutan (acuan: 10–20 baris), bukan per baris secara terisolasi, agar konteks percakapan terjaga.
- Suhu (temperature) model untuk terjemahan diatur rendah (acuan: 0–0,2) agar hasil stabil dan tidak kreatif berlebihan.
- Dukungan mode hemat: terjemahan massal dengan mesin terjemahan, dan LLM hanya untuk baris ambigu, idiom, dan nama.

## 8. Arsitektur dan teknologi yang disarankan

Arsitektur berikut adalah rekomendasi, bukan keputusan final. Keputusan final dicatat di Bagian 17 sebagai pertanyaan terbuka.

### 8.1 Komponen utama

- **Antarmuka (frontend):** satu halaman alur utama — sumber, bahasa, mulai, kemajuan, pratinjau, unduh. Pengaturan lanjutan dilipat (collapsed) secara bawaan.
- **API dan orkestrator:** menerima pekerjaan, menjalankan router jalur, membagi pekerjaan menjadi chunk, mengatur antrean, dan menggabungkan hasil akhir.
- **Worker transkripsi:** menjalankan faster-whisper atau API speech-to-text eksternal, tergantung konfigurasi dan ketersediaan GPU.
- **Worker OCR:** menjalankan OCR khusus bahasa hardsub pada ROI, hanya untuk Jalur 3.
- **Worker fusi:** menyelaraskan hasil OCR dan Whisper berdasarkan timestamp untuk Jalur 3.
- **Worker terjemahan:** mengatur routing per pasangan bahasa antara mesin terjemahan dan LLM, menerapkan glosarium, dan memeriksa konsistensi.
- **Penyimpanan:** penyimpanan objek untuk file sumber, hasil antara per chunk, dan hasil final, dengan masa simpan (retention) yang jelas dan dapat dihapus pengguna.
- **Cache model:** lokasi model yang persisten dan terverifikasi, agar pekerjaan berikutnya tidak mengunduh ulang model berukuran besar (model Whisper besar dapat berukuran sekitar 1,5 GB).

### 8.2 Pilihan komputasi

| Pilihan | Kelebihan | Kekurangan | Cocok untuk |
|---|---|---|---|
| CPU lokal | Gratis, privat, tanpa kuota | Terlalu lambat untuk jalur berat | Jalur 1, dan Jalur 2 untuk klip sangat pendek |
| GPU gratis (mis. Colab T4 / Kaggle) | Jauh lebih cepat, biaya nol | Kuota dan sesi terbatas, tidak stabil untuk layanan publik | Pengembangan, uji coba, pemakaian pribadi |
| GPU berbayar / server sendiri | Cepat dan dapat dikendalikan | Biaya dan perawatan infrastruktur | Layanan publik skala kecil–menengah |
| API speech-to-text / LLM | Tercepat untuk pengguna, tanpa mengelola GPU | Biaya per menit/token, data keluar ke pihak ketiga | Jalan pintas paling realistis untuk MVP publik |

Rekomendasi: dukung lebih dari satu pilihan komputasi di balik antarmuka yang sama. Pengguna memilih mode "lokal / cloud gratis / API" dengan konsekuensi waktu dan biaya yang ditampilkan sebelum pekerjaan dimulai.

### 8.3 Catatan kompatibilitas yang harus dijaga

- Versi library pemrosesan audio/video dan library Whisper harus dikunci (pinned) dan diuji bersama. Pada uji coba pernah terjadi ketidakcocokan antara versi decoder audio (PyAV) dan faster-whisper yang menyebabkan kegagalan membaca metadata, dan harus diatasi dengan memuat audio melalui jalur alternatif (memuat WAV dengan pustaka standar dan NumPy). Kejadian seperti ini harus dicegah dengan pengujian lingkungan otomatis, bukan ditemukan pengguna.
- Pustaka OCR harus diuji pada versi Python dan sistem operasi target yang sebenarnya, bukan hanya di mesin pengembang. Pada uji coba Colab dengan Python 3.13, sebuah pustaka OCR tidak menerima masukan berupa gambar PIL secara langsung dan hanya menerima path file, array NumPy, bytes, atau objek Path, dan sebuah opsi OCR GPU yang direkomendasikan ternyata tidak memiliki paket (wheel) untuk Python 3.13 tersebut.
- Setiap sel atau langkah pemrosesan yang menulis ke folder harus membuat folder tersebut terlebih dahulu, karena sesi cloud dapat dimulai ulang dan menghapus folder kerja.

## 9. Strategi terjemahan

### 9.1 Prinsip: tidak ada satu metode terbaik untuk semua kasus

Terjemahan paling akurat untuk subtitle, berdasarkan riset yang sudah dibahas, diperoleh dari kombinasi: **LLM dengan konteks dan glosarium, ditambah proofreading manusia**. Mesin terjemahan khusus adalah pilihan kedua yang sangat kuat untuk kecepatan dan konsistensi, sedangkan terjemahan mesin umum yang kaku berada di urutan terakhir untuk dialog drama.

Alasannya:

- LLM menerjemahkan dengan konteks adegan: siapa yang berbicara, baris sebelumnya, sarkasme, slang, dan tingkat kesopanan (honorifik) pada bahasa Korea, Mandarin, dan Jepang. Mesin terjemahan per baris tidak memiliki konteks tersebut.
- Glosarium membuat nama tokoh konsisten di seluruh video. Tanpa glosarium, nama yang sama dapat diterjemahkan berbeda-beda antarbaris.
- LLM dapat diminta menghasilkan subtitle yang pendek dan natural, bukan terjemahan harfiah yang panjang.

### 9.2 Routing model per pasangan bahasa

Tidak ada satu LLM yang menang mutlak untuk semua bahasa. Rekomendasi routing awal, yang harus divalidasi ulang dengan pengujian pada konten Suba sendiri sebelum dikunci:

| Pasangan bahasa | Rekomendasi utama | Alternatif / catatan |
|---|---|---|
| Korea → Indonesia | Gemini (kelas Pro) | Kuat pada bahasa Korea dalam benchmark yang dibahas |
| Jepang → Indonesia | Gemini, dengan pemeriksaan ekstra | Jepang adalah bahasa tersulit bagi semua model; sebagian model yang fasih justru melenceng dari makna asli |
| Mandarin → Indonesia | DeepSeek atau Qwen (termasuk Qwen-MT) | Prioritas bahasa Mandarin lebih kuat, biaya per token lebih rendah |
| Inggris → Indonesia dan sebaliknya | Gemini atau Claude | Keduanya kompetitif; pilih berdasarkan biaya dan pengujian sendiri |
| Subtitle secara khusus, mode lokal/gratis | TranslateGemma 12B | Model khusus terjemahan yang dalam benchmark subtitle yang dibahas mengungguli beberapa LLM umum |
| Terjemahan massal hemat biaya | Mesin terjemahan khusus (mis. DeepL) | Terukur cepat dan stabil untuk volume besar; LLM hanya untuk baris sulit |

Angka benchmark eksternal yang disebut selama riset (misalnya peringkat pada WMT25 dan laporan industri 2025–2026) bersifat sebagai petunjuk awal, bukan jaminan. Sebelum rilis, Suba harus memiliki set uji sendiri: beberapa adegan per pasangan bahasa, dinilai manusia untuk akurasi makna, kealamian, dan konsistensi nama.

### 9.3 Mode terjemahan yang didukung

- **Mode cepat:** seluruh baris diterjemahkan mesin terjemahan khusus. Cocok untuk draf dan konten non-drama.
- **Mode seimbang (bawaan yang disarankan):** mesin terjemahan untuk sebagian besar baris, LLM untuk baris ambigu, idiom, baris dengan kepercayaan transkripsi rendah, dan baris yang mengandung nama dari glosarium.
- **Mode kualitas:** seluruh adegan diterjemahkan LLM dengan konteks dan glosarium. Paling lambat dan paling mahal, ditujukan untuk rilis yang akan dipublikasikan.

### 9.4 Batasan yang tidak dapat dihilangkan oleh terjemahan

Terjemahan tidak dapat memperbaiki sumber yang salah. Kesalahan OCR atau Whisper akan diterjemahkan dengan setia menjadi kesalahan dalam bahasa target. Karena itu urutan yang benar adalah: bersihkan dan koreksi sumber terlebih dahulu, baru terjemahkan. Antarmuka koreksi di Bagian 6.2 adalah bagian dari fitur kualitas, bukan tambahan kosmetik.

## 10. Konteks multimodal: apakah LLM dapat "menonton" videonya?

LLM teks saja hanya melihat transkrip. Konteksnya terbatas pada baris sebelum dan sesudahnya. LLM multimodal (misalnya kelas Gemini, GPT, dan Qwen-VL) dapat menerima video, audio, dan teks dalam satu jendela konteks, sehingga konteks terjemahannya lebih kaya: siapa yang berbicara, ekspresi, lokasi adegan, teks yang muncul di layar, label produk, dan benda yang ditunjuk pembicara.

Manfaat praktis untuk Suba:

- Membedakan makna kata yang sama berdasarkan situasi visual.
- Menyelaraskan terjemahan dengan teks resmi yang tampil di layar, misalnya tulisan pada tombol atau papan nama.
- Membantu menentukan pembicara pada adegan dengan banyak tokoh.
- Membaca teks incidental di frame, misalnya pesan chat yang muncul pada siaran langsung.

Batasan yang harus diakui:

- Model multimodal umumnya mengambil sampel frame (acuan umum: sekitar 1 frame per detik), sehingga detail yang sangat cepat dapat terlewat.
- Video panjang (misalnya 170 menit) mahal dari sisi token jika seluruh video dikirim. Video harus dibagi per adegan.
- Model tetap dapat berhalusinasi, yaitu menebak detail visual yang sebenarnya tidak ada.
- Klaim efisiensi dari vendor, misalnya mode pencarian frame selektif yang diklaim jauh lebih hemat token, adalah klaim vendor dan harus diuji sendiri sebelum dijadikan dasar desain.

Keputusan desain: OCR dan Whisper tetap menjadi sumber teks dan timing yang akurat. Konteks multimodal dipakai sebagai lapisan tambahan pada tahap terjemahan, berupa keyframe per adegan yang dikirim bersama kelompok baris yang diterjemahkan — bukan sebagai pengganti pipeline utama.

## 11. Masalah yang diketahui

Bagian ini adalah daftar masalah yang benar-benar ditemui atau teridentifikasi selama riset. Setiap masalah dicatat dengan dampak dan mitigasinya, agar tidak ditemukan ulang saat pengembangan.

### 11.1 Performa adalah masalah utama

- **CPU lokal terlalu lambat.** Whisper untuk audio 85 detik membutuhkan 126,6 detik di CPU, dan OCR untuk video 170 menit membutuhkan sekitar 8,5 jam di CPU. Dampak: pengguna akan menilai tool gagal. Mitigasi: routing jalur, GPU/API untuk jalur berat, dan larangan menjadikan CPU sebagai mode bawaan untuk video panjang.
- **Model besar memperlambat awal pekerjaan.** Pemuatan model saja terukur 16,3 detik, dan ukuran model dapat mencapai sekitar 1,5 GB. Mitigasi: cache persisten, model dimuat sekali dan dipakai ulang antar-chunk, model kecil untuk draf.
- **Pengolahan sekuensial membuang waktu.** Jika chunk diproses satu per satu dan hasil baru ditampilkan di akhir, waktu tunggu terasa jauh lebih lama. Mitigasi: pemrosesan paralel per chunk dan hasil bertahap.
- **Penghematan yang diasumsikan besar ternyata kecil.** Frame differencing hanya menghemat sekitar 23% pada video dengan latar bergerak, bukan 70–80%. Mitigasi: ukur setiap optimasi pada video nyata sebelum mengklaim manfaatnya.
- **Penyimpanan frame yang boros.** Menyimpan ribuan frame sebagai file gambar ke disk memperlambat proses dan memenuhi penyimpanan. Mitigasi: proses frame di memori, simpan hanya keyframe yang dibutuhkan untuk pratinjau dan konteks multimodal.

### 11.2 Hambatan platform sumber

- **Pemeriksaan bot pada YouTube.** Klien pengunduh standar dapat diblokir oleh pemeriksaan bot, sementara klien lain hanya berhasil menampilkan daftar subtitle tanpa berhasil mengunduhnya. Mitigasi: sediakan lebih dari satu metode pengambilan softsub, dan tampilkan pesan yang jujur jika semua metode gagal, termasuk opsi mengunggah file secara manual.
- **Pembatasan permintaan (rate limit).** Pengambilan subtitle sempat terkena RequestBlocked dan baru berhasil setelah jeda. Mitigasi: jeda dan percobaan ulang dengan backoff, cache hasil pengambilan, dan jangan menembak platform secara beruntun.
- **Perubahan platform yang tidak terprediksi.** Metode yang bekerja hari ini dapat berhenti bekerja setelah platform mengubah API atau kebijakannya. Mitigasi: pisahkan modul pengambilan per platform agar dapat diperbaiki tanpa menyentuh pipeline inti.

### 11.3 Akurasi transkripsi dan OCR

- **Whisper salah dengar nama dan kata mirip bunyi.** Pada uji live berbahasa Korea, sebuah kata kerja umum terbaca sebagai kata lain yang bunyinya mirip dan kemudian diterjemahkan menjadi frasa yang sama sekali salah makna ("masuk penjara"), nama penyanyi asing ternama terbaca menjadi nama lain yang mirip, dan sebuah kata lain terbaca menjadi nama yang tidak ada. Dampak: kesalahan kecil di sumber menjadi kesalahan besar dan memalukan di terjemahan. Mitigasi: daftar nama dan istilah dari glosarium dipakai untuk memeriksa hasil, baris dengan kepercayaan rendah ditandai untuk diperiksa manusia, dan pengguna dianjurkan memeriksa nama secara khusus.
- **OCR bergantung pada bahasa dan kualitas gambar.** Teks kecil, font bergaya, teks bergerak, dan kontras rendah menurunkan akurasi. Bahasa dengan karakter kompleks dan bahasa yang secara umum sulit (termasuk Jepang dalam konteks terjemahan) membutuhkan pengujian tersendiri. Mitigasi: ROI yang tepat, peningkatan resolusi pada area subtitle saja, dan pilihan model OCR per bahasa.
- **Fusi OCR dan Whisper dapat memilih sumber yang salah.** Jika kedua sumber berbeda, aturan pemilihan yang buruk menghasilkan teks yang lebih buruk dari keduanya. Mitigasi: aturan fusi berbasis kepercayaan dan kesepakatan antar-sumber, dengan mode pratinjau yang menunjukkan kedua sumber untuk segmen yang bertentangan.
- **Bahasa audio dan bahasa hardsub bisa berbeda.** Mengasumsikan keduanya sama menghasilkan OCR dengan model bahasa yang salah. Mitigasi: dua pengaturan bahasa yang terpisah dan terdeteksi secara terpisah.

### 11.4 Akurasi dan konsistensi terjemahan

- **Kesalahan sumber terbawa ke semua bahasa target.** Lihat Bagian 9.4. Mitigasi: tahap pembersihan sumber sebelum terjemahan.
- **Nama tokoh tidak konsisten tanpa glosarium.** Mitigasi: glosarium per proyek dan pemeriksaan konsistensi otomatis setelah terjemahan.
- **Terjemahan harfiah yang terlalu panjang.** Baris yang benar secara makna dapat tetap gagal sebagai subtitle jika tidak muat dibaca dalam durasi tampilnya. Mitigasi: batas karakter per baris, pemecahan baris otomatis, dan instruksi gaya subtitle pada prompt terjemahan.
- **Register dan honorifik hilang.** Bahasa Korea, Jepang, dan Mandarin memiliki tingkat kesopanan yang tidak selalu memiliki padanan langsung dalam bahasa Indonesia. Mitigasi: konteks adegan untuk LLM dan catatan gaya per proyek (formal, santai, atau campuran).

### 11.5 Kompatibilitas dan lingkungan

- **Ketidakcocokan versi library.** Pernah terjadi kegagalan akibat versi decoder audio yang tidak cocok dengan versi faster-whisper. Mitigasi: kunci versi, uji lingkungan otomatis, dan sediakan jalur cadangan untuk memuat audio.
- **Model terunduh ulang tanpa perlu.** Pada uji coba, sistem mencoba mengunduh ulang model sekitar 1,5 GB dari repositori lain padahal cache lokal sudah lengkap. Mitigasi: pemeriksaan cache eksplisit dan penggunaan path model lokal yang terverifikasi sebelum pekerjaan dimulai.
- **Perbedaan perilaku pustaka antarversi Python.** Sebuah pustaka OCR berperilaku berbeda di Colab Python 3.13 dan rekomendasi GPU-nya tidak tersedia untuk versi tersebut. Mitigasi: uji pada lingkungan target yang sebenarnya dan catat matriks kompatibilitas.
- **Sesi cloud yang dimulai ulang menghapus pekerjaan.** Folder kerja di lingkungan notebook cloud hilang setelah restart, dan langkah yang tidak membuat ulang foldernya akan gagal. Mitigasi: desain resume per chunk dan pembuatan folder yang idempoten di setiap langkah.

### 11.6 Biaya, privasi, dan pengalaman pengguna

- **Biaya API dapat membengkak pada video panjang.** Biaya speech-to-text dan LLM dihitung per menit atau per token, sehingga video 170 menit dengan konteks multimodal penuh dapat menjadi mahal. Mitigasi: perkiraan biaya sebelum mulai, mode seimbang sebagai bawaan, dan keyframe selektif bukan seluruh video.
- **Privasi file pengguna.** Mengirim video ke API pihak ketiga berarti data meninggalkan perangkat pengguna. Mitigasi: mode lokal untuk pengguna yang membutuhkannya, penjelasan yang jelas sebelum mode cloud dipilih, dan penghapusan file sumber sesuai kebijakan retensi.
- **Alur teknis mengusir pengguna umum.** Notebook dengan banyak sel yang harus dijalankan manual terbukti menjadi hambatan pada riset awal. Mitigasi: satu alur utama tanpa langkah teknis yang terlihat, seperti di Bagian 6.1.
- **Tidak ada ETA membuat waktu tunggu terasa lebih buruk.** Jalur hardsub yang memang lambat akan terasa gagal jika pengguna tidak tahu berapa lama lagi. Mitigasi: kemajuan per chunk, ETA yang diperbarui, dan unduhan parsial.
- **Hak cipta dan ketentuan platform.** Pengguna bertanggung jawab atas hak atas konten yang mereka proses. Suba harus menampilkan pengingat singkat mengenai hal ini dan tidak memasarkan diri sebagai alat untuk mengambil konten terkunci atau berbayar milik pihak lain.

## 12. Solusi performa yang disarankan

Solusi disusun berdasarkan urutan dampak terbesar, bukan urutan kemudahan.

### 12.1 Urutan solusi

1. **Routing terlebih dahulu.** Selalu coba Jalur 1 sebelum Jalur 2, dan Jalur 2 sebelum Jalur 3. Ini adalah penghematan terbesar dan tidak membutuhkan biaya apa pun.
2. **Pindahkan komputasi berat ke GPU atau API.** CPU lokal hanya untuk Jalur 1 dan klip pendek. Untuk produk publik, API adalah jalan pintas paling realistis; untuk pemakaian pribadi, GPU gratis adalah titik awal yang wajar.
3. **Chunk, paralel, dan resume.** Potong pekerjaan menjadi chunk sekitar 10 menit, proses beberapa chunk secara paralel sesuai kapasitas, simpan hasil per chunk, dan lanjutkan dari kegagalan tanpa mengulang.
4. **Model bertingkat.** Model kecil untuk draf, timing, dan deteksi awal. Model besar hanya untuk hasil final dan baris dengan kepercayaan rendah. Prinsip yang sama berlaku untuk OCR: model ringan, ROI saja, dan laju frame awal 1 fps.
5. **Hemat pada terjemahan, bukan pada akurasi sumber.** Terjemahan massal dengan mesin terjemahan, LLM hanya untuk baris sulit. Jangan menghemat dengan menurunkan kualitas transkripsi sumber, karena kesalahan di sana berlipat ganda di semua bahasa target.
6. **Tampilkan hasil secara bertahap.** Hasil per chunk yang langsung dapat diperiksa membuat kecepatan yang dirasakan (perceived speed) jauh lebih baik, walaupun total waktu proses sama.
7. **Hilangkan pekerjaan sia-sia yang sudah terbukti.** Jangan mengunduh ulang model yang sudah ada di cache, jangan menyimpan ribuan frame yang tidak dibutuhkan, dan jangan memproses ulang chunk yang sudah selesai.

### 12.2 Target performa untuk MVP

| Skenario | Target |
|---|---|
| Video 15 menit dengan softsub | Selesai dalam hitungan detik, tanpa menjalankan Whisper/OCR |
| Video 10 menit, Jalur Whisper, GPU gratis | Selesai di bawah 10 menit (di bawah 1x durasi) |
| Video 10 menit, Jalur Whisper, GPU berbayar / API | Selesai di bawah 5 menit |
| Video hardsub 170 menit, GPU T4 | Tidak lebih buruk dari baseline terukur sekitar 2,5 jam, dengan ETA dan hasil per chunk |
| Pekerjaan terputus di tengah | Dapat dilanjutkan tanpa kehilangan chunk yang sudah selesai |

Jika target Jalur Whisper di GPU tidak tercapai dan waktu proses tetap di atas 1x durasi, MVP belum siap dirilis sebagai tool umum dan harus diposisikan secara jujur sebagai alat bantu semi-otomatis, bukan alat instan.

## 13. Persyaratan non-fungsional

- **Keandalan:** kegagalan satu chunk tidak menggagalkan seluruh pekerjaan. Setiap chunk dapat dicoba lagi secara terpisah.
- **Transparansi:** jalur yang dipilih, model yang dipakai, perkiraan waktu, dan perkiraan biaya ditampilkan sebelum dan selama pekerjaan berjalan.
- **Keterbacaan hasil:** SRT yang dihasilkan valid secara format, timestamp tidak tumpang tindih, dan baris mematuhi batas karakter yang diatur.
- **Keamanan data:** file sumber dan hasil hanya dapat diakses pemilik pekerjaan, dengan tautan unduhan yang tidak dapat ditebak dan masa berlaku terbatas jika produk bersifat publik.
- **Penghapusan:** pengguna dapat menghapus proyek beserta file sumber dan hasil antaranya secara permanen.
- **Pengamatan (observability):** setiap pekerjaan mencatat jalur, durasi per tahap, model dan versi library yang dipakai, serta alasan kegagalan per chunk, agar masalah kompatibilitas dapat dilacak dari log, bukan dari tebakan.
- **Bahasa antarmuka:** antarmuka awal berbahasa Indonesia, dengan struktur yang memungkinkan bahasa lain ditambahkan kemudian.

## 14. Roadmap

### 14.1 MVP — Whisper-first dan softsub

- Masukan URL dan unggahan file.
- Router Jalur 1 dan Jalur 2, dengan Jalur 3 belum dibuka untuk umum.
- Chunking, resume, cache model, dan hasil bertahap per chunk.
- Ekspor SRT bahasa sumber dan satu bahasa target.
- Terjemahan mode seimbang: mesin terjemahan untuk massal, LLM untuk baris sulit.
- Glosarium nama sederhana yang dapat diedit pengguna.
- Target pengguna awal: pemakaian pribadi dan penguji terbatas, di GPU gratis atau API.

### 14.2 Versi 1 — Hardsub dan koreksi

- Jalur 3 dibuka dengan deteksi ROI, pilihan bahasa hardsub terpisah dari bahasa audio, fusi OCR + Whisper, dan ETA eksplisit.
- Pratinjau koreksi per segmen dengan keyframe.
- Pemeriksaan konsistensi nama dan penandaan baris kepercayaan rendah.
- Ekspor VTT dan transkrip teks biasa.

### 14.3 Versi 2 — Konteks multimodal dan kualitas

- Keyframe per adegan dikirim ke LLM multimodal pada tahap terjemahan.
- Routing terjemahan per pasangan bahasa yang sudah divalidasi dengan set uji internal.
- Mode kualitas penuh untuk rilis publik, termasuk catatan gaya dan register per proyek.
- Dasbor riwayat proyek, penggunaan biaya API, dan pengaturan retensi.

Urutan ini disengaja: fitur yang paling cepat dan paling sering dipakai dirilis lebih dulu, sedangkan jalur terberat dirilis setelah fondasi chunking, resume, dan koreksi sudah terbukti.

## 15. Metrik keberhasilan

- **Kecepatan:** rasio waktu proses terhadap durasi video (realtime factor) per jalur. Target Jalur 2 di GPU adalah di bawah 1,0 dan Jalur 1 mendekati 0.
- **Keberhasilan pekerjaan:** persentase pekerjaan yang selesai tanpa intervensi teknis dari pengguna.
- **Kualitas transkripsi:** tingkat kesalahan kata (word error rate) pada set uji internal per bahasa, diukur terpisah untuk audio bersih dan audio sulit (musik latar, banyak pembicara, siaran langsung).
- **Kualitas terjemahan:** penilaian manusia pada sampel adegan per pasangan bahasa untuk akurasi makna, kealamian, dan konsistensi nama. Penilaian otomatis saja tidak cukup.
- **Waktu sampai hasil pertama:** waktu dari menekan tombol mulai sampai chunk pertama dapat dilihat pengguna.
- **Biaya per menit video:** total biaya GPU/API dibagi durasi, dilaporkan per jalur dan per mode terjemahan.
- **Retensi koreksi:** seberapa banyak koreksi pengguna pada draf otomatis. Jika pengguna harus mengoreksi hampir setiap baris, kualitas otomatis belum memadai walaupun prosesnya cepat.

## 16. Risiko utama

| Risiko | Dampak | Mitigasi awal |
|---|---|---|
| Performa GPU gratis tidak stabil atau kuotanya berubah | MVP terasa lambat dan tidak dapat diandalkan | Dukungan API sebagai jalur alternatif sejak awal |
| Platform sumber mengubah cara akses subtitle | Jalur 1 berhenti bekerja untuk platform tersebut | Modul per platform, opsi unggah file manual |
| Biaya LLM multimodal membengkak | Mode kualitas tidak ekonomis | Keyframe selektif, mode seimbang sebagai bawaan |
| Akurasi bahasa tertentu jauh di bawah bahasa lain | Pengguna bahasa tersebut mendapat pengalaman buruk | Set uji per bahasa, rilis bahasa secara bertahap dengan label kualitas |
| Kesalahan nama dan idiom lolos ke rilis publik | Reputasi hasil Suba buruk | Penandaan kepercayaan rendah dan alur koreksi sebelum ekspor final |
| Ketergantungan pada satu penyedia model | Kenaikan harga atau perubahan kebijakan menghentikan fitur | Lapisan routing yang memungkinkan penggantian penyedia per pasangan bahasa |

## 17. Pertanyaan terbuka yang harus diputuskan sebelum pengembangan

- Bentuk produk final: aplikasi web, aplikasi desktop lokal, atau keduanya? Keputusan ini menentukan pilihan komputasi dan model privasi.
- J : belum tau,sepertinya berbentuk script cli atau google colab juga bisa dipertimbangkan
- Sumber komputasi bawaan untuk publik: GPU yang dikelola sendiri atau API pihak ketiga?
- J : GPU Server Komputasi, karena Device Lokal PC saya tidak punya GPU
- Bahasa rilis pertama: apakah Korea, Mandarin, Jepang, dan Inggris dirilis bersamaan, atau bertahap berdasarkan hasil set uji per bahasa?
- J : Korea, Mandarin, English
- Batas ukuran file, durasi maksimum, dan masa simpan file sumber untuk setiap tingkat pengguna.
- J : tidak ada, karena hanya tool untuk diri sendiri tidak untuk publik
- Model penetapan harga jika produk dibuka untuk publik: berdasarkan menit video, berdasarkan biaya API ditambah margin, atau langganan?
- J : Tidak dibuka untuk publik, tapi hal ini mungkin terjadi dimasa depan
- Siapa yang menilai set uji terjemahan internal, dan berapa sampel minimum per pasangan bahasa sebelum sebuah bahasa dinyatakan siap?
- J : Kurang paham pertanyaan ini
- Apakah konteks multimodal masuk ke MVP sebagai eksperimen terbatas, atau ditunda sepenuhnya ke Versi 2 seperti pada roadmap saat ini?
- J : Kurang paham pertanyaan ini

## 18. Kesimpulan keputusan

Suba layak dikembangkan sebagai tool umum, dengan satu syarat yang tidak dapat ditawar: performa harus dibuktikan per jalur dengan angka, bukan diasumsikan. Bukti yang sudah ada menunjukkan softsub bersifat instan, Whisper dapat menjadi cukup cepat di GPU atau API, dan hardsub akan selalu menjadi mode lambat khusus yang harus diberi ETA dan ekspektasi yang jujur.

Karena itu keputusan yang direkomendasikan adalah memulai dari MVP Whisper-first ditambah softsub, menunda jalur hardsub sampai fondasi chunking, resume, cache, dan koreksi terbukti, serta menerapkan routing terjemahan per bahasa dengan glosarium sejak awal. Dengan urutan tersebut, Suba menyelesaikan masalah yang paling sering terjadi dengan kecepatan yang benar-benar terasa sebagai tool, bukan sebagai skrip lambat yang dibungkus antarmuka.
