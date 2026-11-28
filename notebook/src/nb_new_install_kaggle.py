# OCR GPU (RapidOCR 3.x, 2026-11-27) — varian Kaggle: tanpa install cublas
# (CUDA libs sudah ada di image Kaggle), tapi build onnxruntime-gpu harus
# cocok dengan CUDA image-nya: CUDA 13 -> >=1.27, CUDA 12 -> <1.27.
# (Colab saat ini CUDA 13.0; Kaggle kemungkinan masih CUDA 12.)
# JALUR KAGGLE INI BELUM PERNAH DITES END-TO-END — kalau cell OCR gagal
# di assert CUDA, kirim log-nya sebelum mengubah apa pun.
!pip install -q rapidocr faster-whisper ipywidgets matplotlib
import glob
_cuda_dirs = sorted(glob.glob('/usr/local/cuda-*/'))
_cuda13 = any('cuda-13' in d for d in _cuda_dirs)
_ort = 'onnxruntime-gpu>=1.27' if _cuda13 else 'onnxruntime-gpu<1.27'
_cudnn = 'nvidia-cudnn-cu13' if _cuda13 else 'nvidia-cudnn-cu12'
print('CUDA dirs:', _cuda_dirs, '-> ORT:', _ort, '| cuDNN:', _cudnn)
import subprocess
subprocess.run(['pip', 'install', '-q', _ort, _cudnn], check=True)
!apt-get -qq update && apt-get -qq install -y fonts-noto-core fonts-dejavu-core || true
!ffmpeg -version | head -1
!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
