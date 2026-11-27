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
# Default dynamic sejak 2026-11-27: band statis mengaburkan wajah/kulit di
# area yang tidak ada teks (leher di detik ~89) dan radius kecil meninggalkan
# bayangan glyph Mandarin di latar gelap (detik ~5). Dynamic hanya blur di
# tempat teks berada, saat teks tampil (+ padding waktu).
BLUR_MODE = "dynamic"
ALWAYS_BLUR = True      # True: band selalu blur (OCR miss tidak bikin Mandarin bocor)
BLUR_RADIUS = 20        # 12 terlalu lemah: glyph putih di latar gelap masih
                        # kelihatan sebagai bercak; 20 + power 3 menghilangkannya
BLUR_TIME_PAD = 0.4     # dynamic: jendela blur diperlebar ±0.4 detik supaya
                        # tidak miss kalau timing OCR meleset sedikit
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
# Polish: baris yang diterjemah lewat MyMemory/Google (paling lemah) dilewatkan
# sekali lagi lewat LLM supaya bahasanya natural seperti dialog drama.
# Tidak jalan kalau TIPROUTER_API_KEY kosong; DeepL tidak ikut di-polish
# karena kualitasnya sudah bagus. Matikan dengan POLISH_WITH_LLM = False
# kalau tidak mau ada biaya LLM tambahan (±3 batch untuk 45 baris).
POLISH_WITH_LLM = True
# API key: pakai Colab Secret "TIPROUTER_API_KEY" / env var, atau tempel di sini
TIPROUTER_API_KEY = ""   # <-- tempel di sini kalau tidak pakai Colab secret
DEEPL_API_KEY = ""
# ===================================================

PER_EP_DIR = os.path.join(BASE_OUT_DIR, "per_episode")
HARDSUB_EP_DIR = os.path.join(BASE_OUT_DIR, "episodes_hardsub_id")
MERGED_DIR = os.path.join(BASE_OUT_DIR, "merged")
WORK_DIR = os.path.join(BASE_OUT_DIR, "work")
CACHE_PATH = os.path.join(WORK_DIR, "translate_cache.json")
CACHE_PROV_PATH = os.path.join(WORK_DIR, "translate_cache_prov.json")

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

# Provider per baris cache: "deepl" / "google" / "mymemory" / "llm" /
# "polished" / tidak ada (= cache lama, provider tidak tercatat).
# Dipakai polish supaya baris yang sudah di-polish tidak di-polish lagi
# di run berikutnya, dan baris DeepL tidak ikut di-polish.
_cache_prov = {}
if os.path.exists(CACHE_PROV_PATH):
    try:
        with open(CACHE_PROV_PATH, encoding="utf-8") as f:
            _cache_prov = json.load(f)
    except Exception:
        _cache_prov = {}


def save_cache():
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)
    tmp = CACHE_PROV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache_prov, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PROV_PATH)

print("Episodes dir         :", EPISODES_DIR)
print("Per-episode SRT/JSON :", PER_EP_DIR)
print("Hardsub ID dir       :", HARDSUB_EP_DIR)
print("Merged dir           :", MERGED_DIR)
print("Blur mode            :", BLUR_MODE, "| always:", ALWAYS_BLUR)
print("Cache terjemahan     :", len(_cache), "entri")
