import json, os

# ================= EDIT BAGIAN INI =================
EPISODES_DIR = "/content/drive/MyDrive/duanju/episodes"
BASE_OUT_DIR = "/content/drive/MyDrive/duanju/suba_hardsub"
MAX_EPISODES = 200

# --- Parameter OCR ---
FPS = 1                 # sampling; 0.5 lebih cepat, timing subtitle kasar
ROI = (0.05, 0.62, 0.95, 0.93)   # (x_min, y_min, x_max, y_max) rasio 0.0 - 1.0
MIN_CONF = 0.65
UPSCALE = 2             # 1080p+up2 seakurat 960+up3, 1.6x lebih cepat
MAX_WIDTH = 1080        # frame lebih lebar dari ini di-resize sebelum crop
BATCH_SIZE = 8          # frame per panggilan OCR (det per frame, rec satu batch)
MIN_DUR = 0.35          # segmen lebih pendek dari ini dibuang
TEXT_GATE = True        # skip frame tanpa teks putih terang (hemat ~70% OCR)
TEXT_GATE_MIN_BRIGHT = 0.05
CHUNK_SECONDS = 600     # checkpoint OCR per chunk, aman di-interrupt

# --- Parameter Blur & Hardsub ---
# "static"  = 1 band vertikal FIXED + time-gate (blur hanya nyala saat ada teks) -> murah
# "dynamic" = box per segmen (tinggi dikunci ke band) -> presisi, tapi N crop+blur+overlay
BLUR_MODE = "static"
ALWAYS_BLUR = True      # True: band selalu blur (OCR miss tidak bikin Mandarin bocor)
BLUR_RADIUS = 12        # 15+ mulai merusak background
BLUR_PAD_X = 0.02
BLUR_PAD_Y = 0.012
PROGRESS_PCT = 10       # print progress ffmpeg tiap N persen
FONT_NAME = "Noto Sans"

# --- Parameter Translate ---
LLM_URL = "https://tiprouter.my.id/v1/chat/completions"
LLM_MODELS = ["auto", "deepseek-v4.1-flash-1017"]   # diuji: hanya ini yang tersedia di akun
LLM_BATCH = 20
LLM_TIMEOUT = 180
FREE_DELAY = 0.5
# API key: pakai Colab Secret "TIPROUTER_API_KEY" / env var, atau tempel di sini
TIPROUTER_API_KEY = ""   # <-- tempel di sini kalau tidak pakai Colab secret
DEEPL_API_KEY = ""
# ===================================================

PER_EP_DIR = os.path.join(BASE_OUT_DIR, "per_episode")
HARDSUB_EP_DIR = os.path.join(BASE_OUT_DIR, "episodes_hardsub_id")
MERGED_DIR = os.path.join(BASE_OUT_DIR, "merged")
WORK_DIR = os.path.join(BASE_OUT_DIR, "work")
CACHE_PATH = os.path.join(WORK_DIR, "translate_cache.json")

for d in (PER_EP_DIR, HARDSUB_EP_DIR, MERGED_DIR, WORK_DIR):
    os.makedirs(d, exist_ok=True)


# ---- API key: Colab Secret > env > cell konfigurasi ----
def _get_secret(name, fallback=""):
    try:
        from google.colab import userdata
        v = userdata.get(name)
        if v:
            return str(v).strip()
    except Exception:
        pass
    return (os.environ.get(name) or fallback or "").strip()


TIPROUTER_API_KEY = _get_secret("TIPROUTER_API_KEY", TIPROUTER_API_KEY)
DEEPL_API_KEY = _get_secret("DEEPL_API_KEY", DEEPL_API_KEY)

_cache = {}
if os.path.exists(CACHE_PATH):
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}


def save_cache():
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)

print("Episodes dir         :", EPISODES_DIR)
print("Per-episode SRT/JSON :", PER_EP_DIR)
print("Hardsub ID dir       :", HARDSUB_EP_DIR)
print("Merged dir           :", MERGED_DIR)
print("Blur mode            :", BLUR_MODE, "| always:", ALWAYS_BLUR)
print("Cache terjemahan     :", len(_cache), "entri")
