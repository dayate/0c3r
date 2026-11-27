#!/usr/bin/env python3
"""Suba local — hardsub OCR pipeline (Mandarin -> Indonesia), tanpa Colab.

HANYA UNTUK TESTING. Jalur utama adalah notebook Colab (notebook/src/).
File ini adalah cermin untuk testing lokal, bukan sumber kebenaran.
Cell Whisper timing + fusi hanya ada di notebook; di lokal timing tetap
mengikuti OCR (±1 detik).

Alur per episode: probe -> extract frame (fps sampling) -> OCR (ROI, gated, batched)
-> dedupe jadi segmen -> translate (gratis DeepL -> Google -> MyMemory, LLM fallback)
-> SRT zh/id -> render hardsub (blur band subtitle + burn sub ID, satu pass).

Input  : ./input/*.mp4
Output : ./output/per_episode/  ./output/hardsub/  ./output/merged/
Kerja  : ./work/frames|chunks|cache   Log: ./log.txt

Env:
  TIPROUTER_API_KEY  (wajib untuk translate LLM; tanpa ini langsung fallback gratis)
  DEEPL_API_KEY      (opsional, fallback kedua)

Contoh:  .venv\\Scripts\\python.exe local_pipeline.py --limit 1
"""

import argparse
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PER_EP_DIR = os.path.join(OUTPUT_DIR, "per_episode")
HARDSUB_DIR = os.path.join(OUTPUT_DIR, "hardsub")
MERGED_DIR = os.path.join(OUTPUT_DIR, "merged")
WORK_DIR = os.path.join(BASE_DIR, "work")
FRAME_DIR = os.path.join(WORK_DIR, "frames")
CHUNK_DIR = os.path.join(WORK_DIR, "chunks")
CACHE_DIR = os.path.join(WORK_DIR, "cache")
TR_CACHE_PATH = os.path.join(CACHE_DIR, "translate_cache.json")
LOG_FILE = os.path.join(BASE_DIR, "log.txt")


# ───────────────────────── config ─────────────────────────
def _load_config():
    p = os.path.join(BASE_DIR, "suba_config.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


CFG = _load_config()
CHUNK_SECONDS = int(CFG.get("MAX_CHUNK_DURATION") or CFG.get("CHUNK_SECONDS") or 600)
MAX_EPISODES = int(CFG.get("MAX_EPISODES") or 0)  # 0 = semua

FPS = 1                 # sampling; 0.5 lebih cepat, 1 lebih presisi timing
ROI = (0.05, 0.62, 0.95, 0.93)
MIN_CONF = 0.65
UPSCALE = 2             # diukur: 1080p+up2 akurat sama dgn 960+up3, 1.6x lebih cepat
MAX_WIDTH = 1080        # frame lebih lebar dari ini di-resize sebelum crop
BATCH_SIZE = 8          # frame per panggilan OCR (det per frame, rec satu batch)
MIN_DUR = 0.35          # segmen lebih pendek dari ini dibuang

# Gate murah: subtitle drama putih terang. ROI tanpa pixel putih = tidak ada teks.
# shortcut: subtitle berwarna/gelap bisa lolos gate ini (false negative) -> set False.
TEXT_GATE = True
TEXT_GATE_MIN_BRIGHT = 0.05  # persen pixel sangat terang di ROI

BLUR_RADIUS = 12        # blur statis band subtitle; 15+ mulai merusak background
BLUR_PAD_X = 0.02
BLUR_PAD_Y = 0.012
# static  = satu band vertikal fixed + time-gate (hanya nyala saat ada teks) -> cepat, CPU
# dynamic = box per segmen, presisi maksimal -> N crop+blur+overlay, butuh GPU/Colab
BLUR_MODE = "static"
# True: band blur selalu nyala -> subtitle Mandarin yang tidak terdeteksi OCR tidak bocor
ALWAYS_BLUR = True
PROGRESS_PCT = 10       # print progress ffmpeg tiap N persen
FONT_NAME = "Arial"

LLM_URL = "https://tiprouter.my.id/v1/chat/completions"
LLM_MODELS = ["auto", "deepseek-v4.1-flash-1017"]  # diuji: hanya ini yang tersedia di akun
LLM_BATCH = 20          # segmen per request
LLM_TIMEOUT = 180
FREE_DELAY = 0.5        # jeda antar request translator gratis

MAX_OUTPUT_MB = 0       # 0 = nonaktif; >0 = peringatan keras di log kalau output lebih besar

log = logging.getLogger("suba")


def setup_logging():
    for d in (INPUT_DIR, PER_EP_DIR, HARDSUB_DIR, MERGED_DIR, FRAME_DIR, CHUNK_DIR, CACHE_DIR):
        os.makedirs(d, exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


# ───────────────────────── util ─────────────────────────
def natural_key(path):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def fmt_srt_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    return f"{h:02d}:{m:02d}:{t % 60:06.3f}".replace(".", ",")


def write_srt(segs, path, key):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        idx = 1
        for s in segs:
            txt = (s.get(key) or "").strip()
            if not txt:
                continue
            f.write(f"{idx}\n{fmt_srt_time(s['start'])} --> {fmt_srt_time(s['end'])}\n{txt}\n\n")
            idx += 1
    os.replace(tmp, path)


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_mandarin(text):
    return bool(text and _CJK_RE.search(text))


def _wrap_text(text, max_len=42):
    """Bungkus teks di batas kata jadi baris-baris <= max_len karakter."""
    text = (text or "").strip()
    if not text:
        return []
    lines, cur = [], ""
    for word in text.replace("\n", " ").split(" "):
        if not word:
            continue
        while len(word) > max_len:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:max_len])
            word = word[max_len:]
        cand = (cur + " " + word).strip() if cur else word
        if len(cand) <= max_len:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def normalize_segments(segs):
    """Rapikan segmen supaya lolos validator (cermin nb_new_validate.py):
    potong overlap, bungkus baris > 42 char, pecah segmen yang teksnya
    tetap > 2 baris. Return (segs_baru, stats)."""
    stats = {"trimmed": 0, "dropped": 0, "wrapped": 0, "split": 0}
    ordered = sorted(segs, key=lambda s: (float(s.get("start", 0.0)),
                                          float(s.get("end", 0.0))))
    out = []
    for s in ordered:
        s = dict(s)
        start = float(s.get("start", 0.0))
        end = float(s.get("end", 0.0))
        if not end > start:
            stats["dropped"] += 1
            continue
        for key in ("text_zh", "text_id"):
            txt = (s.get(key) or "").strip()
            if not txt:
                continue
            lines = _wrap_text(txt)
            if len(lines) != len(txt.split("\n")) or any(
                    len(l) > 42 for l in txt.split("\n")):
                stats["wrapped"] += 1
            s[key] = "\n".join(lines)
        lines_id = (s.get("text_id") or "").split("\n")
        lines_zh = (s.get("text_zh") or "").split("\n")
        if len(lines_id) > 2 or len(lines_zh) > 2:
            mid = start + (end - start) / 2.0
            first = dict(s)
            first["end"] = round(mid, 3)
            first["text_id"] = "\n".join(lines_id[:2])
            first["text_zh"] = "\n".join(lines_zh[:2])
            second = dict(s)
            second["start"] = round(mid, 3)
            second["text_id"] = "\n".join(lines_id[2:])
            second["text_zh"] = "\n".join(lines_zh[2:])
            stats["split"] += 1
            out.extend([first, second])
        else:
            out.append(s)
    fixed = []
    for i, s in enumerate(out):
        start = float(s["start"])
        end = float(s["end"])
        if i + 1 < len(out):
            nxt = float(out[i + 1]["start"])
            if end > nxt - 0.04:
                s = dict(s)
                s["end"] = round(nxt - 0.04, 3)
                end = float(s["end"])
                stats["trimmed"] += 1
        if end - start < 0.2:
            stats["dropped"] += 1
            continue
        if end - start > 7.0:
            s = dict(s)
            s["end"] = round(start + 7.0, 3)
            stats["trimmed"] += 1
        fixed.append(s)
    return fixed, stats


def validate_segments(segs, check_id=True):
    """Validator SRT (cermin notebook/src/nb_new_validate.py)."""
    errors = []
    prev_end = None
    for idx, s in enumerate(segs):
        start = float(s.get("start", 0.0))
        end = float(s.get("end", 0.0))
        if not end > start:
            errors.append(f"segmen {idx}: end ({end}) tidak lebih besar dari start ({start})")
            continue
        if prev_end is not None and start < prev_end - 0.001:
            errors.append(f"segmen {idx}: overlap / tidak monoton (start {start} < prev end {prev_end})")
        prev_end = max(prev_end or 0.0, end)
        if end - start < 0.2 - 1e-6 or end - start > 7.0:
            errors.append(f"segmen {idx}: durasi {end - start:.2f}s di luar batas wajar")
        for key in ("text_zh", "text_id"):
            txt = (s.get(key) or "").strip()
            if not txt:
                continue
            if len(txt.split("\n")) > 2:
                errors.append(f"segmen {idx} ({key}): lebih dari 2 baris")
            for line in txt.split("\n"):
                if len(line) > 42:
                    errors.append(f"segmen {idx} ({key}): baris {len(line)} karakter, maks 42")
        if check_id:
            txt_id = (s.get("text_id") or "").strip()
            zh = (s.get("text_zh") or "").strip()
            if zh and not txt_id:
                errors.append(f"segmen {idx}: belum diterjemah (text_id kosong)")
            elif txt_id and has_mandarin(txt_id):
                errors.append(f"segmen {idx}: SRT ID masih berisi Mandarin")
    return errors


def assert_valid_segments(segs, where=""):
    errors = validate_segments(segs)
    if errors:
        raise ValueError(f"validator SRT gagal {where}: " + "; ".join(errors[:10]))
    return True


def write_json_atomic(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True)
    try:
        info = json.loads(r.stdout)
        st = info.get("streams") or [{}]
        return (float(info.get("format", {}).get("duration", 0.0)),
                int(st[0].get("width", 0)), int(st[0].get("height", 0)))
    except Exception:
        log.warning("ffprobe gagal baca %s: %s", path, (r.stderr or "").strip()[:200])
        return 0.0, 0, 0


def has_nvenc():
    if not shutil.which("nvidia-smi"):
        return False
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or "GPU" not in r.stdout:
            return False
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True).stdout
        return "h264_nvenc" in enc
    except Exception:
        return False


# ───────────────────────── OCR ─────────────────────────
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def fingerprint():
    return {"fps": FPS, "roi": ROI, "min_conf": MIN_CONF, "upscale": UPSCALE,
            "max_width": MAX_WIDTH, "gate": TEXT_GATE, "gate_min": TEXT_GATE_MIN_BRIGHT}


def load_crop(path):
    """Frame -> (array ROI siap OCR, w, h, crop_w, crop_h, ada_teks)."""
    import numpy as np
    from PIL import Image

    img = Image.open(path).convert("RGB")
    w, h = img.size
    if MAX_WIDTH and w > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, int(h * MAX_WIDTH / w)), Image.LANCZOS)
        w, h = img.size
    crop = img.crop((int(w * ROI[0]), int(h * ROI[1]), int(w * ROI[2]), int(h * ROI[3])))
    cw, ch = crop.size

    gate = True
    if TEXT_GATE:
        a = np.asarray(crop, dtype=np.uint8)
        mx = a.max(axis=2)
        mn = a.min(axis=2)
        bright = ((mx > 235) & ((mx - mn) < 40)).mean() * 100
        gate = bright >= TEXT_GATE_MIN_BRIGHT

    arr = np.asarray(crop)
    if UPSCALE > 1:
        from PIL import Image as I
        arr = np.asarray(I.fromarray(arr).resize((cw * UPSCALE, ch * UPSCALE), I.LANCZOS))
    return arr, w, h, cw, ch, gate


def _bbox(quads, up, cw, ch):
    xs = [float(p[0]) / up for q in quads for p in q]
    ys = [float(p[1]) / up for q in quads for p in q]
    x0 = ROI[0] + (min(xs) / cw) * (ROI[2] - ROI[0])
    x1 = ROI[0] + (max(xs) / cw) * (ROI[2] - ROI[0])
    y0 = ROI[1] + (min(ys) / ch) * (ROI[3] - ROI[1])
    y1 = ROI[1] + (max(ys) / ch) * (ROI[3] - ROI[1])
    clamp = lambda v: round(min(1.0, max(0.0, v)), 4)
    return [clamp(x0), clamp(y0), clamp(x1), clamp(y1)]


def ocr_batch(engine, frames):
    """frames: [(arr, cw, ch)] -> [(text, bbox|None)].
    Det tetap per frame (API 1.2.3 tidak menerima list); rec dijalankan sekali
    untuk semua crop batch -> utilises rec_batch_num internal."""
    results = [("", None)] * len(frames)
    metas, crops = [], []
    for i, (arr, cw, ch) in enumerate(frames):
        boxes, _ = engine.text_detector(arr)
        if boxes is None or len(boxes) < 1:
            continue
        boxes = engine.sorted_boxes(boxes)
        cl = engine.get_crop_img_list(arr, boxes)
        metas.append((i, len(crops), len(cl), boxes))
        crops.extend(cl)

    if not crops:
        return results

    rec, _ = engine.text_recognizer(crops)
    for i, base, n, boxes in metas:
        texts, quads = [], []
        for k in range(n):
            txt = str(rec[base + k][0]).strip()
            if txt and float(rec[base + k][1]) >= MIN_CONF:
                texts.append(txt)
                quads.append(boxes[k])
        if texts:
            results[i] = (" ".join(texts), _bbox(quads, UPSCALE, frames[i][1], frames[i][2]))
    return results


def ocr_chunk(vid_path, start, dur, out_json):
    """Extract + OCR satu chunk, simpan checkpoint. Return list segmen."""
    fd = os.path.join(FRAME_DIR, out_json.rsplit(os.sep, 1)[-1].replace(".json", ""))
    shutil.rmtree(fd, ignore_errors=True)
    os.makedirs(fd, exist_ok=True)

    t0 = time.time()
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", vid_path,
         "-vf", f"fps={FPS}", "-start_number", "0", os.path.join(fd, "f_%06d.png")],
        check=True, capture_output=True)
    frames = sorted(glob.glob(os.path.join(fd, "f_*.png")))
    t_extract = time.time() - t0

    engine = get_engine()
    t0 = time.time()
    parsed = []
    for i in range(0, len(frames), BATCH_SIZE):
        batch = frames[i:i + BATCH_SIZE]
        prepared, keep = [], []
        for f in batch:
            arr, w, h, cw, ch, gate = load_crop(f)
            prepared.append((arr, cw, ch))
            keep.append((f, w, h, gate))
        outs = ocr_batch(engine, prepared) if any(k[3] for k in keep) else [("", None)] * len(batch)
        for (f, w, h, gate), (txt, box) in zip(keep, outs):
            parsed.append((txt if gate else "", box, w, h))
    t_ocr = time.time() - t0

    # gabung frame berurutan dengan teks sama -> segmen
    segs, cur_text, cur_start, cur_boxes = [], None, None, []
    for idx, (txt, box, w, h) in enumerate(parsed):
        t = start + idx / FPS
        if not txt:
            if cur_text is not None:
                segs.append({"start": round(cur_start, 3), "end": round(t, 3),
                             "text_zh": cur_text, "bbox": _merge_boxes(cur_boxes)})
                cur_text, cur_start, cur_boxes = None, None, []
            continue
        if txt == cur_text:
            if box:
                cur_boxes.append(box)
            continue
        if cur_text is not None:
            segs.append({"start": round(cur_start, 3), "end": round(t, 3),
                         "text_zh": cur_text, "bbox": _merge_boxes(cur_boxes)})
        cur_text, cur_start, cur_boxes = txt, t, ([box] if box else [])
    if cur_text is not None:
        end_t = start + dur
        segs.append({"start": round(cur_start, 3), "end": round(max(end_t, cur_start + 1.0 / FPS), 3),
                     "text_zh": cur_text, "bbox": _merge_boxes(cur_boxes)})

    segs = [s for s in segs if s["end"] - s["start"] >= MIN_DUR]
    write_json_atomic(out_json, {"start": start, "end": start + dur, "frames": len(frames),
                                 "fingerprint": fingerprint(), "segments": segs})
    log.info("[ocr] chunk %s..%ss frames=%d berteks=%d segmen=%d extract=%.1fs ocr=%.1fs",
             f"{start:.0f}", f"{start + dur:.0f}", len(frames),
             sum(1 for p in parsed if p[0]), len(segs), t_extract, t_ocr)
    shutil.rmtree(fd, ignore_errors=True)
    return segs, t_extract, t_ocr


def _merge_boxes(boxes):
    if not boxes:
        return None
    x0 = max(0.0, min(b[0] for b in boxes))
    y0 = max(0.0, min(b[1] for b in boxes))
    x1 = min(1.0, max(b[2] for b in boxes))
    y1 = min(1.0, max(b[3] for b in boxes))
    if x1 <= x0 or y1 <= y0:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def extract_segments(vid_path, dur):
    """OCR per chunk dengan checkpoint; chunk selesai dilewati saat resume."""
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    cdir = os.path.join(CHUNK_DIR, stem)
    os.makedirs(cdir, exist_ok=True)
    fp = fingerprint()
    segs, totals = [], {"extract": 0.0, "ocr": 0.0}

    starts = []
    s = 0.0
    while s < max(dur, 0.1):
        starts.append(s)
        s += CHUNK_SECONDS

    for start in starts:
        cend = min(start + CHUNK_SECONDS, dur if dur > 0 else start + CHUNK_SECONDS)
        cpath = os.path.join(cdir, f"chunk_{int(start):06d}.json")
        data = None
        if os.path.exists(cpath):
            try:
                with open(cpath, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("fingerprint") != fp:
                    log.info("[ocr] chunk %s tidak cocok config, ulang", os.path.basename(cpath))
                    data = None
            except Exception:
                data = None
        if data is None:
            got, te, to = ocr_chunk(vid_path, start, cend - start, cpath)
            segs.extend(got)
            totals["extract"] += te
            totals["ocr"] += to
        else:
            log.info("[ocr] chunk %s sudah ada, dilewati", os.path.basename(cpath))
            segs.extend(data.get("segments", []))

    segs.sort(key=lambda x: x["start"])
    return segs, totals


# ───────────────────────── translate ─────────────────────────
_cache = {}
_deepl = None
_google = None
_mymemory = None


def load_cache():
    global _cache
    try:
        with open(TR_CACHE_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}
    log.info("cache terjemahan dimuat: %d entri", len(_cache))


def save_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)
    write_json_atomic(TR_CACHE_PATH, _cache)


def _strip_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt).rstrip("`").strip()
    i, j = txt.find("["), txt.rfind("]")
    return txt[i:j + 1] if i >= 0 and j > i else txt


def llm_translate(lines):
    api_key = (os.environ.get("TIPROUTER_API_KEY") or "").strip()
    if not api_key:
        return None
    system = ("Kamu penerjemah subtitle drama Mandarin ke bahasa Indonesia. "
              "Terjemahkan tiap baris secara natural dan ringkas, jangan menambah penjelasan. "
              "Balas HANYA JSON array of string, jumlah dan urutan sama dengan input.")
    body = {"temperature": 0.2,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(lines, ensure_ascii=False)}]}
    for model in LLM_MODELS:
        for attempt in range(2):
            payload = dict(body, model=model)
            req = urllib.request.Request(
                LLM_URL, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + api_key})
            try:
                with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                out = json.loads(_strip_json(resp["choices"][0]["message"]["content"]))
                if isinstance(out, list) and len(out) == len(lines):
                    return [str(x).strip() for x in out]
                log.warning("LLM %s: jumlah baris tidak cocok", model)
            except urllib.error.HTTPError as e:
                log.warning("LLM %s HTTP %s", model, e.code)
                if e.code in (429, 500, 502, 503):
                    time.sleep(2.0 * (attempt + 1))
                    continue
                break
            except Exception as e:
                log.warning("LLM %s gagal: %s: %s", model, type(e).__name__, str(e)[:120])
                time.sleep(1.0)
    return None


def deepl_translate(text):
    global _deepl
    key = (os.environ.get("DEEPL_API_KEY") or "").strip()
    if not key:
        return None
    try:
        if _deepl is None:
            from deep_translator import DeepLTranslator
            _deepl = DeepLTranslator(api_key=key, source="zh", target="id")
        return _deepl.translate(text) or None
    except Exception as e:
        log.warning("DeepL gagal: %s", str(e)[:100])
        return None


def google_translate(text):
    """Return (teks, provider) — provider 'google' atau 'mymemory'."""
    global _google, _mymemory
    try:
        if _google is None:
            from deep_translator import GoogleTranslator
            _google = GoogleTranslator(source="zh-CN", target="id")
        time.sleep(FREE_DELAY)
        out = _google.translate(text)
        if out and out.strip():
            return out.strip(), "google"
    except Exception:
        pass
    try:
        if _mymemory is None:
            from deep_translator import MyMemoryTranslator
            _mymemory = MyMemoryTranslator(source="zh-CN", target="id-ID")
        time.sleep(FREE_DELAY)
        out = _mymemory.translate(text)
        if out and out.strip():
            return out.strip(), "mymemory"
    except Exception as e:
        log.warning("[tr] gratis gagal: %s", str(e)[:100])
    return None, None


def llm_translate_single(text):
    """Retry per baris lewat LLM. Return teks Indonesia atau None."""
    out = llm_translate([text])
    if out and out[0] and out[0] != text and not has_mandarin(out[0]):
        return out[0]
    return None


def translate_segments(segs):
    """Gratis dulu (DeepL -> Google -> MyMemory), sisa gagal baru LLM batch,
    lalu LLM per baris. Return (segs, failed_list).

    Jaminan: tidak ada baris yang dibiarkan Mandarin di text_id.
    """
    todo = []
    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if not zh:
            s["text_id"] = ""
        elif zh in _cache:
            s["text_id"] = _cache[zh]
        else:
            todo.append(zh)

    uniq = list(dict.fromkeys(todo))
    stats = {"deepl": 0, "google": 0, "mymemory": 0, "llm": 0}
    failed = []
    for n, zh in enumerate(uniq, 1):
        out = deepl_translate(zh)
        if out and out != zh:
            _cache[zh] = out
            stats["deepl"] += 1
            continue
        out, prov = google_translate(zh)
        if out and out != zh:
            _cache[zh] = out
            stats[prov] += 1
        else:
            failed.append(zh)
        if n % 10 == 0:
            log.info("[tr] gratis %d/%d (gagal %d)", n, len(uniq), len(failed))
    save_cache()

    if failed:
        log.warning("[tr] %d baris -> LLM fallback", len(failed))
        for i in range(0, len(failed), LLM_BATCH):
            chunk = failed[i:i + LLM_BATCH]
            out = llm_translate(chunk)
            if out:
                for zh, id_ in zip(chunk, out):
                    if id_ and id_ != zh and not has_mandarin(id_):
                        _cache[zh] = id_
                        stats["llm"] += 1
            log.info("[tr] LLM %d/%d", min(i + LLM_BATCH, len(failed)), len(failed))
            save_cache()

    still_failed = [zh for zh in failed
                    if zh not in _cache or has_mandarin(_cache.get(zh, zh))]
    if still_failed:
        log.warning("[tr] %d baris -> LLM per baris (retry terakhir)", len(still_failed))
        for n, zh in enumerate(still_failed, 1):
            out = llm_translate_single(zh)
            if out:
                _cache[zh] = out
                stats["llm"] += 1
            if n % 5 == 0:
                save_cache()
        save_cache()

    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if zh:
            cand = _cache.get(zh)
            s["text_id"] = cand if (cand and not has_mandarin(cand)) else ""

    done = sum(1 for s in segs if s.get("text_id"))
    failed_final = [{"start": s.get("start"), "end": s.get("end"),
                     "text_zh": (s.get("text_zh") or "").strip(),
                     "reason": "all_providers_failed"}
                    for s in segs
                    if (s.get("text_zh") or "").strip() and not s.get("text_id")]
    log.info("[tr] DeepL=%d Google=%d MyMemory=%d LLM=%d gagal=%d | %d/%d segmen",
             stats["deepl"], stats["google"], stats["mymemory"], stats["llm"],
             len(failed_final), done, len(segs))
    return segs, failed_final


# ───────────────────────── render ─────────────────────────
def _sub_path(p):
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _ass_time(t):
    t = max(0.0, float(t))
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(segs, path, vw, vh, font_size, margin_v):
    """ASS dengan PlayRes = ukuran video, supaya FontSize/MarginV presisi pixel.
    libass men-scale force_style terhadap script 384x288 kalau pakai SRT langsung."""
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {vw}\nPlayResY: {vh}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT_NAME},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,2,1,2,30,30,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [header]
    for s in segs:
        txt = (s.get("text_id") or "").strip().replace("\r", "").replace("\n", "\\N")
        if not txt:
            continue
        lines.append(f"Dialogue: 0,{_ass_time(s['start'])},{_ass_time(s['end'])},Default,,0,0,0,,{txt}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))



def _pct(vals, q):
    v = sorted(vals)
    if len(v) == 1:
        return v[0]
    i = (len(v) - 1) * q / 100.0
    lo, hi = int(i), min(int(i) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def compute_band(segs, vh):
    """Band blur statis dari bbox teks, tahan outlier OCR.
    Outlier (box sempit/tinggi karena deteksi rusak) dibuang, lalu y dipotong
    p10-p90 supaya tidak melebar ke konten atas/bawah. x tetap full extent
    (kalau dipotong, huruf Mandarin di baris terpanjang bisa lolos tanpa blur)."""
    boxes = [s["bbox"] for s in segs if s.get("bbox")]
    if not boxes:
        return None
    mh = _pct([b[3] - b[1] for b in boxes], 50)
    mw = _pct([b[2] - b[0] for b in boxes], 50)
    keep = [b for b in boxes if (b[3] - b[1]) <= 1.6 * mh and (b[2] - b[0]) >= 0.4 * mw]
    if len(keep) < max(3, len(boxes) // 2):
        keep = boxes
    if len(keep) >= 8:
        y0, y1 = _pct([b[1] for b in keep], 10), _pct([b[3] for b in keep], 90)
    else:
        y0, y1 = min(b[1] for b in keep), max(b[3] for b in keep)
    x0 = max(0.0, min(b[0] for b in keep) - BLUR_PAD_X)
    x1 = min(1.0, max(b[2] for b in keep) + BLUR_PAD_X)
    y0 = max(0.0, y0 - BLUR_PAD_Y)
    y1 = min(1.0, y1 + BLUR_PAD_Y)
    if (x1 - x0) <= 0.05 or (y1 - y0) * vh < 24:
        return None
    return (x0, y0, x1, y1)


def _rect(b, vw, vh):
    x = max(0, int(b[0] * vw)) // 2 * 2
    y = max(0, int(b[1] * vh)) // 2 * 2
    w = max(16, int((b[2] - b[0]) * vw) // 2 * 2)
    h = max(16, int((b[3] - b[1]) * vh) // 2 * 2)
    return x, y, min(w, vw - x), min(h, vh - y)


def build_blur(segs, band, vw, vh, mode):
    """Return (filter_complex_prefix, label_output) atau (None, None).
    static: satu rect fixed; ALWAYS_BLUR=True -> overlay selalu nyala (OCR miss aman),
    False -> hanya pada window tiap segmen. dynamic: rect per segmen (paling presisi)."""
    def blur(h):
        r = max(2, min(BLUR_RADIUS, h // 2 - 1))
        return (f"boxblur=luma_radius={r}:luma_power=2:"
                f"chroma_radius={max(1, r // 2)}:chroma_power=1")

    if mode == "dynamic":
        chain, cur = [], "[0:v]"
        # tinggi fixed dari band (kalau ada) supaya tiap box tidak melebar vertikal
        fy = fh = None
        if band:
            _, fy, _, fh = _rect(band, vw, vh)
        for i, s in enumerate(segs):
            b = s.get("bbox")
            if not b:
                continue
            x, y, w, h = _rect(b, vw, vh)
            if fy is not None:
                y, h = fy, fh
                w = max(16, min(x + w, vw) - x)
            chain.append(
                f"{cur}split=2[bi{i}][vm{i}];[bi{i}]crop={w}:{h}:{x}:{y},{blur(h)}[bb{i}];"
                f"[vm{i}][bb{i}]overlay={x}:{y}:enable='between(t,{s['start']},{s['end']})'[o{i}]")
            cur = f"[o{i}]"
        return (";".join(chain), cur) if chain else (None, None)

    if not band:
        return None, None
    x, y, w, h = _rect(band, vw, vh)
    if ALWAYS_BLUR:
        return (f"[0:v]split=2[main][cut];[cut]crop={w}:{h}:{x}:{y},{blur(h)}[b];"
                f"[main][b]overlay={x}:{y}[bg]", "[bg]")
    win = "+".join(f"between(t,{s['start']},{s['end']})" for s in segs if s.get("bbox"))
    return (f"[0:v]split=2[main][cut];[cut]crop={w}:{h}:{x}:{y},{blur(h)}[b];"
            f"[main][b]overlay={x}:{y}:enable='{win}'[bg]", "[bg]")


def run_ffmpeg(cmd, dur, tag):
    """Jalankan ffmpeg (cmd sudah termasuk output), log progress tiap PROGRESS_PCT%."""
    full = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    p = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, bufsize=1)
    step = max(1, PROGRESS_PCT)
    nxt = step
    for line in p.stdout:
        if not line.startswith("out_time_us="):
            continue
        try:
            sec = int(line.split("=", 1)[1]) / 1e6
        except ValueError:
            continue
        if dur > 0 and sec * 100 / dur >= nxt:
            log.info("[%s] %d%% (%.1fs)", tag, min(100, int(sec * 100 / dur)), sec)
            nxt += step
    err = (p.stderr.read() or "").strip()
    p.wait()
    return p.returncode, err


def render_hardsub(vid_path, srt_path, out_mp4, segs, vw, vh, blur_mode=None):
    # None = baca global saat dipanggil (default arg statis tidak ikut --blur)
    blur_mode = blur_mode or BLUR_MODE
    use_nvenc = has_nvenc()
    band = compute_band(segs, vh)
    log.info("[blur] band=%s mode=%s segmen=%d radius=%d always=%s",
             tuple(round(v, 3) for v in band) if band else None, blur_mode,
             sum(1 for s in segs if s.get("bbox")), BLUR_RADIUS, ALWAYS_BLUR)

    font_size = max(20, round(vw * 0.042))
    if band:
        center_y = (band[1] + band[3]) / 2
        margin_v = max(8, int(round((1 - center_y) * vh - font_size * 0.55)))
    else:
        margin_v = int(vh * 0.06)

    ass_path = os.path.join(WORK_DIR, os.path.splitext(os.path.basename(out_mp4))[0] + ".ass")
    write_ass(segs, ass_path, vw, vh, font_size, margin_v)
    log.info("[sub] %d baris font=%d margin_v=%d",
             sum(1 for s in segs if (s.get("text_id") or "").strip()), font_size, margin_v)
    sub = f"ass=filename='{_sub_path(ass_path)}'"

    blur_prefix, bg_label = build_blur(segs, band, vw, vh, blur_mode) if band else (None, None)
    if blur_prefix and bg_label:
        # blur_prefix berakhir dengan bg_label (output overlay); chain ass di atasnya
        fc = f"{blur_prefix};{bg_label}{sub}[v]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-filter_complex", fc,
               "-map", "[v]", "-map", "0:a?", "-c:a", "copy"]
    elif band:
        log.info("[blur] build_blur gagal, fallback ke tanpa blur")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-vf", sub, "-map", "0:v:0",
               "-map", "0:a?", "-c:a", "copy"]
    else:
        log.info("[blur] tidak ada bbox teks, blur dilewati")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-vf", sub, "-map", "0:v:0",
               "-map", "0:a?", "-c:a", "copy"]

    variants = []
    if use_nvenc:
        variants.append(["-c:v", "h264_nvenc", "-preset", "p6", "-cq", "24"])
    variants.append(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])

    dur = probe(vid_path)[0]
    t0 = time.time()
    for enc in variants:
        full = cmd + enc + ["-movflags", "+faststart", out_mp4]
        log.info("[render] enc=%s", enc[1])
        rc, err = run_ffmpeg(full, dur, "render")
        if rc == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 0:
            enc_name = enc[1]
            log.info("[render] selesai enc=%s %.1fs", enc_name, time.time() - t0)
            size_mb = os.path.getsize(out_mp4) / 1048576
            src_mb = os.path.getsize(vid_path) / 1048576
            log.info("ukuran output %.1f MB (source %.1f MB, %.1fx)", size_mb, src_mb,
                     size_mb / src_mb if src_mb else 0)
            if MAX_OUTPUT_MB and size_mb > MAX_OUTPUT_MB:
                log.warning("output melebihi MAX_OUTPUT_MB=%s", MAX_OUTPUT_MB)
            return enc_name, time.time() - t0
        log.warning("[render] %s gagal: %s", enc[1], err[-300:])
        if os.path.exists(out_mp4):
            os.remove(out_mp4)
    raise RuntimeError("semua encoder gagal")


# ───────────────────────── pipeline ─────────────────────────
def process_episode(vid_path, render):
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    ep_json = os.path.join(PER_EP_DIR, f"{stem}_ocr.json")
    zh_srt = os.path.join(PER_EP_DIR, f"{stem}_zh.srt")
    id_srt = os.path.join(PER_EP_DIR, f"{stem}_id.srt")
    out_mp4 = os.path.join(HARDSUB_DIR, f"{stem}_id_hardsub.mp4")

    t_start = time.time()
    timings = {"extract": 0.0, "ocr": 0.0, "translate": 0.0, "render": 0.0}
    dur, vw, vh = probe(vid_path)
    log.info("==== %s | %.1fs %dx%d ====", stem, dur, vw, vh)

    if os.path.exists(ep_json):
        with open(ep_json, encoding="utf-8") as f:
            payload = json.load(f)
        # Resume per episode: cek fingerprint konfigurasi. Kalau berubah,
        # hasil lama tidak dipakai — episode diulang.
        if payload.get("fingerprint") != fingerprint():
            log.info("config berubah, ulang OCR: %s", stem)
            payload = None
        else:
            segs = payload.get("segments", [])
            if not os.path.exists(id_srt) or not os.path.exists(zh_srt):
                write_srt(segs, zh_srt, "text_zh")
                write_srt(segs, id_srt, "text_id")
            log.info("pakai hasil OCR sebelumnya: %d segmen", len(segs))
    else:
        payload = None

    if payload is None:
        segs, totals = extract_segments(vid_path, dur)
        timings.update(totals)
        t0 = time.time()
        segs, failed_final = translate_segments(segs)
        timings["translate"] = time.time() - t0
        if failed_final:
            review_path = os.path.join(PER_EP_DIR, f"{stem}_review.json")
            write_json_atomic(review_path, {"episode": stem, "failed": failed_final})
            raise RuntimeError(
                f"translate gagal {len(failed_final)} baris di {stem} "
                f"(lihat {review_path})")
        segs, _nstats = normalize_segments(segs)
        log.info("normalisasi: dipotong=%d dibuang=%d dibungkus=%d dipecah=%d",
                 _nstats["trimmed"], _nstats["dropped"], _nstats["wrapped"], _nstats["split"])
        assert_valid_segments(segs, where=f"translate {stem}")
        write_json_atomic(ep_json, {
            "episode": stem, "video_file": os.path.basename(vid_path),
            "duration": round(dur, 3), "width": vw, "height": vh,
            "fingerprint": fingerprint(), "segments": segs})
        write_srt(segs, zh_srt, "text_zh")
        write_srt(segs, id_srt, "text_id")

    if render and not os.path.exists(out_mp4):
        assert_valid_segments(segs, where=f"render {stem}")
        _, t_render = render_hardsub(vid_path, id_srt, out_mp4, segs, vw, vh)
        timings["render"] = t_render

    total = time.time() - t_start
    done = sum(1 for s in segs if s.get("text_id") and s["text_id"] != s.get("text_zh"))
    log.info("== %s selesai: %d segmen (%d diterjemah) total %.1fs | extract=%.1f ocr=%.1f "
             "translate=%.1f render=%.1f", stem, len(segs), done, total,
             timings["extract"], timings["ocr"], timings["translate"], timings["render"])
    return {"episode": stem, "video_seconds": dur, "segments": len(segs),
            "translated": done, "total": total, **timings}


def merge_outputs(limit=0):
    jsons = sorted(glob.glob(os.path.join(PER_EP_DIR, "*_ocr.json")), key=natural_key)
    if limit:
        jsons = jsons[:limit]
    merged, chapters, offset = [], [], 0.0
    for jf in jsons:
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
        chapters.append(f"{int(offset // 3600):02d}:{int(offset % 3600 // 60):02d}:{int(offset % 60):02d} - {data.get('episode')}")
        for s in data.get("segments", []):
            merged.append({"start": offset + float(s["start"]), "end": offset + float(s["end"]),
                           "text_zh": (s.get("text_zh") or "").strip(),
                           "text_id": (s.get("text_id") or "").strip()})
        offset += float(data.get("duration", 0.0))

    write_srt(merged, os.path.join(MERGED_DIR, "merged_all_id.srt"), "text_id")
    write_srt(merged, os.path.join(MERGED_DIR, "merged_all_zh.srt"), "text_zh")
    with open(os.path.join(MERGED_DIR, "chapters.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(chapters))
    log.info("merge SRT: %d episode, %d baris, durasi %.1f menit", len(jsons), len(merged), offset / 60)


def merge_videos(limit=0):
    vids = sorted(glob.glob(os.path.join(HARDSUB_DIR, "*_id_hardsub.mp4")), key=natural_key)
    if limit:
        vids = vids[:limit]
    if not vids:
        return
    total_mb = sum(os.path.getsize(v) for v in vids) / 1048576
    lst = os.path.join(WORK_DIR, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for v in vids:
            f.write("file '" + v.replace("\\", "/").replace("'", "'\\''") + "'\n")
    out = os.path.join(MERGED_DIR, "merged_all_episodes_id_hardsub.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", out], capture_output=True, text=True)
    if r.returncode == 0:
        log.info("merge video: %d episode, %.0f MB -> %s", len(vids), total_mb, out)
    else:
        log.warning("merge video gagal: %s", (r.stderr or "").strip()[-300:])


def main():
    global BLUR_MODE
    ap = argparse.ArgumentParser(description="Suba local hardsub pipeline")
    ap.add_argument("--limit", type=int, default=0, help="proses maksimal N episode")
    ap.add_argument("--no-render", action="store_true", help="hanya OCR+translate+SRT")
    ap.add_argument("--no-merge", action="store_true", help="lewati merge akhir")
    ap.add_argument("--blur", choices=("static", "dynamic"), default=BLUR_MODE,
                    help="static = 1 band time-gated (CPU); dynamic = box per segmen (GPU/Colab)")
    args = ap.parse_args()

    BLUR_MODE = args.blur

    setup_logging()
    log.info("Suba local start | log=%s | input=%s", LOG_FILE, INPUT_DIR)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        log.error("ffmpeg/ffprobe tidak ada di PATH"); return 1

    exts = (".mp4", ".mkv", ".webm", ".mov", ".avi")
    videos = sorted([p for p in glob.glob(os.path.join(INPUT_DIR, "*"))
                     if p.lower().endswith(exts)], key=natural_key)
    if MAX_EPISODES:
        videos = videos[:MAX_EPISODES]
    if args.limit:
        videos = videos[:args.limit]
    if not videos:
        log.warning("tidak ada video di %s", INPUT_DIR)
        return 0
    log.info("%d video, chunk=%ss fps=%s gate=%s blur=%s always=%s", len(videos), CHUNK_SECONDS,
             FPS, TEXT_GATE, BLUR_MODE, ALWAYS_BLUR)

    load_cache()
    results = []
    t_all = time.time()
    done_video_sec, done_wall = 0.0, 0.0
    for i, vid in enumerate(videos, 1):
        log.info("--- [%d/%d] %s", i, len(videos), os.path.basename(vid))
        try:
            r = process_episode(vid, render=not args.no_render)
        except Exception as e:
            log.exception("episode gagal: %s", os.path.basename(vid))
            log.error("skip %s: %s", os.path.basename(vid), e)
            continue
        results.append(r)
        done_video_sec += r["video_seconds"]
        done_wall += r["total"]
        if i < len(videos) and done_video_sec > 0:
            eta = (done_wall / done_video_sec) * (sum(probe(v)[0] for v in videos[i:]))
            log.info("ETA sisa %d episode: ~%.1f menit", len(videos) - i, eta / 60)

    save_cache()
    if not args.no_merge:
        merge_outputs(args.limit)
        merge_videos(args.limit)

    log.info("=== summary: %d episode, video %.1f menit, wall %.1f menit ===",
             len(results), done_video_sec / 60, (time.time() - t_all) / 60)
    for k in ("extract", "ocr", "translate", "render"):
        log.info("  %-10s %7.1fs", k, sum(r.get(k, 0) for r in results))
    log.info("log lengkap: %s", LOG_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
