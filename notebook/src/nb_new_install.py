!pip install -q rapidocr-onnxruntime==1.2.3 deep-translator faster-whisper ipywidgets matplotlib
!apt-get -qq update && apt-get -qq install -y fonts-noto-core fonts-dejavu-core
!ffmpeg -version | head -1
!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
