import json, os

# ================= PILIH PROFIL =================
# Profil menyesuaikan device: colab / kaggle / pc / vm / instabox.
# Generator (build_colab_nb.py --profile) mengisi PROFILES + PROFILE di
# bawah ini; kalau cell ini dijalankan apa adanya, yang dipakai adalah
# nilai default profil colab. Ganti PROFILE lalu jalankan ulang cell ini
# untuk pindah profil tanpa generate ulang. Ganti profil = fingerprint
# berubah = cache/checkpoint lama tidak dipakai.
PROFILE = "colab"  # __PROFILE_NAME__
PROFILES = {}  # __PROFILES_JSON__

# ================= EDIT BAGIAN INI (default profil colab) =================
EPISODES_DIR = "/content/drive/MyDrive/duanju/episodes"
BASE_OUT_DIR = "/content/drive/MyDrive/duanju/suba_hardsub"
MAX_EPISODES = 200

# --- Parameter OCR ---
FPS = 1.0               # colab/kaggle 1 fps (Whisper GPU cepat, OCR 2 vCPU
                        # masih sanggup); pc/vm 0,5 fps
ROI = (0.05, 0.55, 0.95, 0.93)   # (x_min, y_min, x_max, y_max) rasio 0.0 - 1.0
MIN_CONF = 0.55         # nilai hasil tuning episode 1 di Colab
UPSCALE = 3             # nilai hasil tuning episode 1 di Colab
MAX_WIDTH = 1080        # frame lebih lebar dari ini di-resize sebelum crop
BATCH_SIZE = 8          # frame per panggilan OCR (det per frame, rec satu batch)
MIN_DUR = 0.35          # segmen lebih pendek dari ini dibuang
TEXT_GATE = True        # skip frame tanpa teks putih terang (hemat ~70% OCR)
TEXT_GATE_MIN_BRIGHT = 0.05
CHUNK_SECONDS = 600     # checkpoint OCR per chunk, aman di-interrupt

# --- Parameter Whisper (timing) ---
# Whisper HANYA dipakai buat timing + cadangan; teks tetap dari OCR.
# Di GPU (colab/kaggle) large-v3-turbo tetap cepat; di CPU (pc/vm)
# pakai "small" beam 1 yang ~4-6x lebih cepat.
WHISPER_MODEL = "large-v3-turbo"
WHISPER_BEAM = 5        # beam 5 (di CPU pakai 1 = greedy, tercepat)
WHISPER_LANG = "zh"

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

# --- Terapkan profil (menimpa nilai default di atas) ---
_p = PROFILES.get(PROFILE, {}) if isinstance(PROFILES, dict) else {}
if _p:
    EPISODES_DIR = _p.get("episodes_dir", EPISODES_DIR)
    BASE_OUT_DIR = _p.get("base_out_dir", BASE_OUT_DIR)
    FPS = float(_p.get("fps", FPS))
    ROI = tuple(_p.get("roi", ROI))
    MIN_CONF = float(_p.get("min_conf", MIN_CONF))
    UPSCALE = int(_p.get("upscale", UPSCALE))
    MAX_WIDTH = int(_p.get("max_width", MAX_WIDTH))
    BATCH_SIZE = int(_p.get("batch_size", BATCH_SIZE))
    MIN_DUR = float(_p.get("min_dur", MIN_DUR))
    WHISPER_MODEL = _p.get("whisper_model", WHISPER_MODEL)
    WHISPER_BEAM = int(_p.get("whisper_beam", WHISPER_BEAM))
    BLUR_MODE = _p.get("blur_mode", BLUR_MODE)
    BLUR_RADIUS = int(_p.get("blur_radius", BLUR_RADIUS))
    BLUR_TIME_PAD = float(_p.get("blur_time_pad", BLUR_TIME_PAD))
    ALWAYS_BLUR = bool(_p.get("always_blur", ALWAYS_BLUR))
    print("Profil:", PROFILE, "|", _p.get("note", ""))

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
