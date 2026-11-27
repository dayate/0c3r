import glob, json, os, re, shutil, subprocess, time

import numpy as np
from PIL import Image

# ========================= util =========================
def natural_key(path):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def fmt_srt_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def write_srt(segs, path, key="text_id"):
    with open(path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segs, 1):
            txt = (seg.get(key) or "").strip()
            if not txt:
                continue
            f.write(f"{idx}\n{fmt_srt_time(seg['start'])} --> {fmt_srt_time(seg['end'])}\n{txt}\n\n")


def write_json_atomic(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def fingerprint():
    # roi harus list (bukan tuple) supaya sama setelah JSON round-trip;
    # kalau tuple, resume chunk/episode tidak pernah cocok dan OCR selalu ulang.
    # profile ikut: ganti profil = setting beda = cache lama tidak dipakai.
    return {"profile": globals().get("PROFILE", "colab"),
            "fps": FPS, "roi": list(ROI), "min_conf": MIN_CONF, "upscale": UPSCALE,
            "max_width": MAX_WIDTH, "gate": TEXT_GATE, "gate_min": TEXT_GATE_MIN_BRIGHT}


# ========================= video / ffmpeg =========================
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


# ========================= OCR =========================
def load_crop(path):
    """Frame -> (array ROI siap OCR, w, h, crop_w, crop_h, ada_teks)."""
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
        arr = np.asarray(Image.fromarray(arr).resize((cw * UPSCALE, ch * UPSCALE), Image.LANCZOS))
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
    Det per frame (API 1.2.3 tidak menerima list), rec satu batch untuk semua crop."""
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


def is_name_card(text, bbox):
    """True kalau segmen ini kartu nama/peran, bukan dialog.

    Kartu perkenalan di duanju vertikal: nama besar + jabatan kecil di
    sampingnya (mis. 韩沐宸 / 丰宸集团总裁), ditulis tegak di kiri layar.
    Ciri: bbox tegak (lebar jauh lebih kecil dari tinggi) DAN teksnya
    berisi kata jabatan, atau teksnya sangat pendek (nama saja).
    Dialog sungguhan hampir selalu horizontal, jadi aturan ini aman.
    """
    if not text or not bbox:
        return False
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if h <= 0 or w >= 0.6 * h or h < 0.10:
        return False
    role_words = ("总裁", "董事长", "总经理", "副总裁", "集团", "董事", "总裁夫人")
    if any(k in text for k in role_words):
        return True
    if len(text.strip()) <= 4:
        return True
    return False


def drop_name_cards(segs):
    """Buang segmen kartu nama/peran dari daftar. Return (segs_baru, jumlah)."""
    kept, dropped = [], 0
    for s in segs:
        if is_name_card(s.get("text_zh") or "", s.get("bbox")):
            dropped += 1
            continue
        kept.append(s)
    return kept, dropped


def ocr_chunk(vid_path, start, dur, out_json):
    """Extract + OCR satu chunk, simpan checkpoint."""
    fd = os.path.join(WORK_DIR, "frames", os.path.splitext(os.path.basename(out_json))[0])
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
        segs.append({"start": round(cur_start, 3),
                     "end": round(max(start + dur, cur_start + 1.0 / FPS), 3),
                     "text_zh": cur_text, "bbox": _merge_boxes(cur_boxes)})

    segs = [s for s in segs if (s["end"] - s["start"]) >= MIN_DUR]
    # Kartu nama/peran bukan dialog: buang supaya tidak diterjemah dan
    # dibakar jadi subtitle (mis. "Presiden Direktur Grup Fengchen 1").
    segs, n_cards = drop_name_cards(segs)
    if n_cards:
        print(f"  [ocr] chunk {start:.0f}-{start + dur:.0f}s kartu nama dibuang: {n_cards}", flush=True)
    write_json_atomic(out_json, {"start": start, "end": start + dur, "frames": len(frames),
                                 "fingerprint": fingerprint(), "segments": segs})
    print(f"  [ocr] chunk {start:.0f}-{start + dur:.0f}s frames={len(frames)} segmen={len(segs)} "
          f"extract={t_extract:.1f}s ocr={t_ocr:.1f}s", flush=True)
    shutil.rmtree(fd, ignore_errors=True)
    return segs, t_extract, t_ocr


def extract_segments(vid_path, dur):
    """OCR per chunk dengan checkpoint; chunk selesai dilewati saat resume."""
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    cdir = os.path.join(WORK_DIR, "chunks", stem)
    os.makedirs(cdir, exist_ok=True)
    fp = fingerprint()
    segs, totals = [], {"extract": 0.0, "ocr": 0.0}

    starts, s = [], 0.0
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
                    print(f"  [ocr] chunk {start:.0f} tidak cocok config, ulang", flush=True)
                    data = None
            except Exception:
                data = None
        if data is None:
            got, te, to = ocr_chunk(vid_path, start, cend - start, cpath)
            segs.extend(got)
            totals["extract"] += te
            totals["ocr"] += to
        else:
            print(f"  [ocr] chunk {start:.0f} sudah ada, dilewati", flush=True)
            segs.extend(data.get("segments", []))

    segs.sort(key=lambda x: x["start"])
    return segs, totals


# ========================= tahap 1: OCR =========================
exts = (".mp4", ".mkv", ".webm", ".mov", ".avi")
videos = sorted([p for p in glob.glob(os.path.join(EPISODES_DIR, "*")) if p.lower().endswith(exts)],
                key=natural_key)[:MAX_EPISODES]
print(f"[ocr] {len(videos)} episode (maks {MAX_EPISODES})", flush=True)

for i, vid_path in enumerate(videos, 1):
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    ep_json = os.path.join(PER_EP_DIR, f"{stem}_ocr.json")
    out_zh_srt = os.path.join(PER_EP_DIR, f"{stem}_zh.srt")
    if os.path.exists(ep_json):
        try:
            with open(ep_json, encoding="utf-8") as f:
                _old = json.load(f)
            # Resume per episode: cek fingerprint konfigurasi. Kalau berubah,
            # hasil lama tidak dipakai — episode diulang dari awal.
            if _old.get("fingerprint") == fingerprint():
                print(f"[ocr] {i}/{len(videos)} {stem}: skip (json ada, config sama)", flush=True)
                continue
            print(f"[ocr] {i}/{len(videos)} {stem}: config berubah, ulang OCR", flush=True)
        except Exception:
            print(f"[ocr] {i}/{len(videos)} {stem}: json rusak, ulang OCR", flush=True)
    dur, vw, vh = probe(vid_path)
    print(f"[ocr] {i}/{len(videos)} {stem} | {dur:.1f}s {vw}x{vh}", flush=True)
    segs, totals = extract_segments(vid_path, dur)
    write_json_atomic(ep_json, {
        "episode": stem, "video_file": os.path.basename(vid_path),
        "duration": round(dur, 3), "width": vw, "height": vh,
        "fingerprint": fingerprint(), "segments": segs})
    write_srt(segs, out_zh_srt, "text_zh")
    print(f"[ocr] {i}/{len(videos)} {stem}: {len(segs)} segmen | "
          f"extract={totals['extract']:.1f}s ocr={totals['ocr']:.1f}s", flush=True)

print("[ocr] selesai", flush=True)
