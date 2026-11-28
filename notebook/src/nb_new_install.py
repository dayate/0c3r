# OCR GPU (RapidOCR 3.x, 2026-11-27 — tes: 8,4x vs CPU, 0,62 vs 5,25 dtk/frame):
# - rapidocr 3.x (model default PP-OCRv6, API baru: out = eng(arr)).
# - onnxruntime-gpu >=1.27 = build CUDA 13. Colab saat ini CUDA 13.0;
#   versi 1.26 (build CUDA 12) TIDAK BISA load dan session-nya diam-diam
#   jatuh ke CPU — cell OCR men-assert CUDA sebelum jalan.
# - nvidia-cudnn-cu13: cuDNN buat CUDA EP (di-preload di cell OCR).
#   nvidia-cublas-cu13 SENGAJA tidak ada: paketnya placeholder 0.0.1 tanpa
#   wheel, dan sistem sudah punya libcublas.so.13.
# - nvidia-cublas-cu12 TETAP ada: Whisper (faster-whisper/CTranslate2) butuh
#   libcublas.so.12. nvidia-cudnn-cu12 DIGANTI cu13: CTranslate2 tidak
#   link cuDNN (dicek via ldd), jadi tidak ada yang butuh cudnn-cu12.
# - onnxruntime-gpu DIPASANG TERAKHIR dengan --force-reinstall --no-deps
#   (2026-11-28): faster-whisper menarik onnxruntime CPU, dan pip
#   memasangnya belakangan sehingga menimpa file GPU — hasilnya kedua
#   paket 1.32.0 terpasang tapi CUDA EP tidak terdaftar (tes manual
#   Taufik di T4). Pasang ulang paksa di akhir memastikan file GPU
#   yang menang; assert di bawah gagal cepat kalau masih CPU.
!pip install -q rapidocr nvidia-cudnn-cu13 faster-whisper ipywidgets matplotlib nvidia-cublas-cu12
!pip install -q --force-reinstall --no-deps "onnxruntime-gpu>=1.27"
import onnxruntime as _ort
assert "CUDAExecutionProvider" in _ort.get_available_providers(), \
    "CUDA EP tidak terdaftar setelah install — cek pip (onnxruntime CPU menimpa GPU?)"
!apt-get -qq update && apt-get -qq install -y fonts-noto-core fonts-dejavu-core
!ffmpeg -version | head -1
!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
