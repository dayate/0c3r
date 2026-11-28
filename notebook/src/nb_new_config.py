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
FPS = 0.5               # semua profil 0,5 fps sejak 2026-11-28 (tes ep 1:
                        # hemat ~60 dtk OCR, hilang ~7 baris — fusi Whisper
                        # menambal timing kasar)
# Mesin OCR (dari profil, lihat profiles.yaml):
#   rapidocr3-gpu = RapidOCR 3.x + onnxruntime-gpu, colab/kaggle (tes: 8,4x
#     lebih cepat dari CPU, 0,62 vs 5,25 dtk/frame, teks identik).
#   rapidocr1-cpu = rapidocr-onnxruntime 1.2.3 CPU, pc/vm/instabox.
OCR_ENGINE = "rapidocr3-gpu"
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
# Semua profil pakai "small" beam 1 (greedy) sejak 2026-11-28 (tes ep 1):
# di T4 tetap cepat dan hemat ~10-15 dtk vs large-v3-turbo beam 5.
WHISPER_MODEL = "small"
WHISPER_BEAM = 1        # beam 1 = greedy, tercepat
WHISPER_LANG = "zh"

# --- Parameter Re-scan (baris hilang) ---
# Segmen Whisper-only (suara ada, OCR tidak menemukan teks) di-OCR ulang
# dengan sampling rapat di sekitar intervalnya + upscale lebih besar.
# Kasus nyata: 睡了 (2 karakter kecil, ~5,5 dtk) dan 干杯 (transisi 55 dtk)
# lolos dari sampling 0,5 fps.
RESCAN_STEP = 0.25      # langkah sampling re-scan (detik)
RESCAN_PAD = 0.2        # perluasan interval re-scan di kedua ujung
RESCAN_UPSCALE = 4      # upscale re-scan (lebih besar dari UPSCALE=3)
RESCAN_MIN_DUR = 0.2    # segmen Whisper-only lebih pendek dari ini tidak di-rescan

# --- Parameter Blur & Hardsub ---
# "none"    = tanpa blur (V0) — subtitle ID dibakar apa adanya, paling cepat
# "static"  = 1 band vertikal FIXED + time-gate (blur hanya nyala saat ada teks) -> murah
# "dynamic" = box per segmen (tinggi dikunci ke band) -> presisi, tapi N crop+blur+overlay
# Default none (V0) sejak 2026-11-28, keputusan Taufik setelah perbandingan
# V0/static/box: V0 tercepat (32,3 dtk vs static 41,2 di T4) dan teks Mandarin
# yang bertabrakan dengan sub ID diterima sebagai trade-off.
BLUR_MODE = "none"
ALWAYS_BLUR = True      # True: band selalu blur (OCR miss tidak bikin Mandarin bocor)
OUTPUT_720P = True      # output 720p (sisi panjang 1280), keputusan 2026-11-28
BLUR_RADIUS = 20        # 12 terlalu lemah: glyph putih di latar gelap masih
                        # kelihatan sebagai bercak; 20 + power 3 menghilangkannya
BLUR_TIME_PAD = 0.4     # dynamic: jendela blur diperlebar ±0.4 detik supaya
                        # tidak miss kalau timing OCR meleset sedikit
BLUR_PAD_X = 0.02
BLUR_PAD_Y = 0.012
PROGRESS_PCT = 10       # print progress ffmpeg tiap N persen
FONT_NAME = "Noto Sans"

# --- Parameter Translate (CipRouter, keputusan 2026-11-28: D1-D4) ---
# Rantai: step-3.7-flash -> auto -> daftar review. Google DIHAPUS (D1:
# 0/41 dan 0/44 di Colab) dan NLLB DIHAPUS total (D3). Key dari Colab
# Secrets TIPROUTER_API_KEY — tidak pernah ditulis di notebook.
CIPROUTER_URL = "https://api.ciprouter.com/v1/chat/completions"
CIPROUTER_MODEL_PRIMARY = "step-3.7-flash"
CIPROUTER_MODEL_FALLBACK = "auto"
CIPROUTER_BATCH = 8
CIPROUTER_TIMEOUT = 120
# Nama/istilah yang diganti di teks ZH SEBELUM dikirim ke translator
# (bukan ke teks ZH yang disimpan): model sering salah menerjemah nama
# orang dan 闺蜜 — kasus nyata 瘟疫 diterjemah jadi "Wabah".
NAME_OVERRIDES = {"温薏": "Wen Yi", "韩沐宸": "Han Muchen", "闺蜜": "sahabat"}
# API key: pakai Colab Secret "TIPROUTER_API_KEY" / env var, atau tempel di sini
TIPROUTER_API_KEY = ""   # <-- tempel di sini kalau tidak pakai Colab secret
# ===================================================

# --- Terapkan profil (menimpa nilai default di atas) ---
_p = PROFILES.get(PROFILE, {}) if isinstance(PROFILES, dict) else {}
if _p:
    EPISODES_DIR = _p.get("episodes_dir", EPISODES_DIR)
    BASE_OUT_DIR = _p.get("base_out_dir", BASE_OUT_DIR)
    FPS = float(_p.get("fps", FPS))
    OCR_ENGINE = _p.get("ocr_engine", OCR_ENGINE)
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

_cache = {}
if os.path.exists(CACHE_PATH):
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}

# Provider per baris cache: "step" / "auto" / "passthrough" /
# tidak ada (= cache lama, provider tidak tercatat).
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
