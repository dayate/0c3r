"""Cell 3c — Tuning OCR (GUI, Colab).

Tujuan: cari konfigurasi OCR yang pas SEBELUM jalanin pipeline penuh.
Pilih video + detik, geser ROI / min_conf / upscale, lihat langsung
teks apa yang ke-detect dan confidence-nya di frame itu.

Cara pakai:
1. Jalankan cell ini (setelah cell Konfigurasi).
2. Pilih video, geser slider detik sampai ketemu frame yang ada subtitlenya.
3. Atur ROI sampai kotaknya pas menutupi area subtitle saja.
4. Tekan "Jalankan OCR" — lihat kotak hijau (hasil detect) dan tabel teksnya.
5. Kalau masih banyak yang kelewat / salah, ubah min_conf atau upscale,
   lalu tekan lagi. Tombol "Uji 5 frame" mengetes 5 detik berurutan.
6. Kalau sudah cocok, tekan "Simpan config" — nilainya ditulis ke
   tuning_config.json DAN dipakai cell OCR berikutnya (ROI, MIN_CONF,
   UPSCALE, MAX_WIDTH, TEXT_GATE di-update di notebook ini).
   Supaya permanen, salin juga baris config yang dicetak ke cell Konfigurasi.
"""
import glob
import json
import os
import re
import subprocess

import numpy as np
from PIL import Image

try:
    import ipywidgets as widgets
    from IPython.display import display
    HAS_WIDGETS = True
except Exception:
    HAS_WIDGETS = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    HAS_MPL = True
except Exception:
    HAS_MPL = False


def _natural_key(path):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _probe(path):
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


def _extract_frame(vid_path, t, out_path):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", vid_path,
         "-frames:v", "1", "-q:v", "2", out_path],
        check=True, capture_output=True)
    return out_path


def _get_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _gate_bright(crop_arr):
    """Persen piksel putih terang di crop (sama seperti TEXT_GATE di OCR)."""
    a = np.asarray(crop_arr, dtype=np.uint8)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    return float(((mx > 235) & ((mx - mn) < 40)).mean() * 100)


def _prepare_crop(img, roi, upscale, max_width):
    """Frame PIL -> (array siap OCR, w, h, crop_w, crop_h)."""
    w, h = img.size
    if max_width and w > max_width:
        img = img.resize((max_width, int(h * max_width / w)), Image.LANCZOS)
        w, h = img.size
    crop = img.crop((int(w * roi[0]), int(h * roi[1]),
                     int(w * roi[2]), int(h * roi[3])))
    cw, ch = crop.size
    arr = np.asarray(crop)
    if upscale > 1:
        arr = np.asarray(Image.fromarray(arr).resize(
            (cw * upscale, ch * upscale), Image.LANCZOS))
    return arr, w, h, cw, ch


def _ocr_frame(engine, arr, min_conf):
    """OCR satu frame. Return [(text, conf, quad)] dengan quad dalam
    koordinat array yang di-OCR (sudah di-upscale)."""
    result, _elapse = engine(arr)
    out = []
    if not result:
        return out
    for box, text, prob in result:
        text = str(text).strip()
        conf = float(prob)
        if text and conf >= min_conf:
            out.append((text, conf, [[float(p[0]), float(p[1])] for p in box]))
    return out


def _draw_result(img, roi, detections, upscale, crop_w, crop_h, out_path):
    """Gambar frame + kotak ROI (merah) + kotak hasil OCR (hijau).
    Return path gambar hasil. Tanpa matplotlib, return None."""
    if not HAS_MPL:
        return None
    w, h = img.size
    fig, ax = plt.subplots(figsize=(7, 12))
    ax.imshow(np.asarray(img))
    ax.add_patch(patches.Rectangle(
        (w * roi[0], h * roi[1]), w * (roi[2] - roi[0]), h * (roi[3] - roi[1]),
        linewidth=2, edgecolor="red", facecolor="none", linestyle="--"))
    for _text, _conf, quad in detections:
        xs = [p[0] / upscale for p in quad]
        ys = [p[1] / upscale for p in quad]
        x0 = w * roi[0] + (min(xs) / crop_w) * w * (roi[2] - roi[0])
        x1 = w * roi[0] + (max(xs) / crop_w) * w * (roi[2] - roi[0])
        y0 = h * roi[1] + (min(ys) / crop_h) * h * (roi[3] - roi[1])
        y1 = h * roi[1] + (max(ys) / crop_h) * h * (roi[3] - roi[1])
        ax.add_patch(patches.Rectangle(
            (x0, y0), x1 - x0, y1 - y0,
            linewidth=2, edgecolor="lime", facecolor="none"))
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def _run_one(engine, vid_path, t, roi, min_conf, upscale, max_width,
             use_gate, gate_min, tmp_dir):
    """OCR satu detik. Return dict hasil untuk ditampilkan."""
    frame_path = os.path.join(tmp_dir, "tune_frame.png")
    _extract_frame(vid_path, t, frame_path)
    img = Image.open(frame_path).convert("RGB")
    arr, w, h, cw, ch = _prepare_crop(img, roi, upscale, max_width)
    bright = _gate_bright(arr if upscale == 1 else np.asarray(
        Image.fromarray(arr).resize((cw, ch), Image.LANCZOS)))
    gated = (not use_gate) or bright >= gate_min
    detections = _ocr_frame(engine, arr, min_conf) if gated else []
    img_path = os.path.join(tmp_dir, "tune_result.png")
    drawn = _draw_result(img, roi, detections, upscale, cw, ch, img_path)
    return {"t": t, "size": (w, h), "bright_pct": round(bright, 2),
            "gated": gated, "detections": detections, "image": drawn,
            "frame": frame_path}


# ========================= UI (hanya di Colab) =========================
if not HAS_WIDGETS:
    print("[tune] ipywidgets tidak tersedia di environment ini, "
          "cell tuning dilewati. Di Colab widget akan muncul.", flush=True)
else:
    _exts = (".mp4", ".mkv", ".webm", ".mov", ".avi")
    _videos = sorted(
        [p for p in glob.glob(os.path.join(EPISODES_DIR, "*"))
         if p.lower().endswith(_exts)], key=_natural_key)
    if not _videos:
        print(f"[tune] tidak ada video di {EPISODES_DIR}. "
              "Taruh video dulu, lalu jalankan cell ini lagi.", flush=True)
    else:
        _tmp = os.path.join(WORK_DIR, "tune")
        os.makedirs(_tmp, exist_ok=True)
        _engine = None

        w_video = widgets.Dropdown(options=_videos, value=_videos[0],
                                   description="Video:", layout=widgets.Layout(width="95%"))
        _dur0, _vw0, _vh0 = _probe(_videos[0])
        w_time = widgets.FloatSlider(value=min(30.0, _dur0 / 2 if _dur0 else 30.0),
                                     min=0, max=_dur0 if _dur0 else 300,
                                     step=1.0, description="Detik:")
        w_roi_x0 = widgets.FloatSlider(value=ROI[0], min=0, max=0.9, step=0.01, description="ROI x0:")
        w_roi_y0 = widgets.FloatSlider(value=ROI[1], min=0, max=0.9, step=0.01, description="ROI y0:")
        w_roi_x1 = widgets.FloatSlider(value=ROI[2], min=0.1, max=1.0, step=0.01, description="ROI x1:")
        w_roi_y1 = widgets.FloatSlider(value=ROI[3], min=0.1, max=1.0, step=0.01, description="ROI y1:")
        w_conf = widgets.FloatSlider(value=MIN_CONF, min=0.3, max=0.95, step=0.01, description="Min conf:")
        w_upscale = widgets.IntSlider(value=UPSCALE, min=1, max=3, step=1, description="Upscale:")
        w_maxw = widgets.IntSlider(value=MAX_WIDTH, min=480, max=1920, step=120, description="Max width:")
        w_gate = widgets.Checkbox(value=TEXT_GATE, description="Text gate (skip frame tanpa teks putih)")
        w_gate_min = widgets.FloatSlider(value=TEXT_GATE_MIN_BRIGHT, min=0.0, max=1.0,
                                         step=0.01, description="Gate min %:")
        btn_run = widgets.Button(description="Jalankan OCR", button_style="primary")
        btn_5 = widgets.Button(description="Uji 5 frame (t, +2, +4, +6, +8 dtk)")
        btn_save = widgets.Button(description="Simpan config", button_style="success")
        out = widgets.Output()

        def _cfg():
            return {"roi": (round(w_roi_x0.value, 2), round(w_roi_y0.value, 2),
                            round(w_roi_x1.value, 2), round(w_roi_y1.value, 2)),
                    "min_conf": round(w_conf.value, 2),
                    "upscale": int(w_upscale.value),
                    "max_width": int(w_maxw.value),
                    "text_gate": bool(w_gate.value),
                    "gate_min": round(w_gate_min.value, 2)}

        def _show(res):
            with out:
                out.clear_output()
                print(f"Detik {res['t']:.0f} | ukuran {res['size'][0]}x{res['size'][1]} | "
                      f"teks putih {res['bright_pct']}% | gate lolos: {res['gated']}")
                if not res["gated"]:
                    print("Frame di-skip text gate (tidak ada teks putih terang di ROI). "
                          "Turunkan 'Gate min %' atau matikan gate untuk mengetes.")
                if not res["detections"]:
                    print("Tidak ada teks terdeteksi. Coba lebarkan ROI, "
                          "turunkan Min conf, atau naikkan Upscale.")
                for text, conf, _quad in res["detections"]:
                    print(f"  {conf:.2f}  {text}")
                if res["image"]:
                    display(Image.open(res["image"]))

        def _on_run(_b):
            global _engine
            if _engine is None:
                _engine = _get_engine()
            cfg = _cfg()
            res = _run_one(_engine, w_video.value, w_time.value, cfg["roi"],
                           cfg["min_conf"], cfg["upscale"], cfg["max_width"],
                           cfg["text_gate"], cfg["gate_min"], _tmp)
            _show(res)

        def _on_5(_b):
            global _engine
            if _engine is None:
                _engine = _get_engine()
            cfg = _cfg()
            with out:
                out.clear_output()
                for k in range(5):
                    t = w_time.value + k * 2
                    res = _run_one(_engine, w_video.value, t, cfg["roi"],
                                   cfg["min_conf"], cfg["upscale"], cfg["max_width"],
                                   cfg["text_gate"], cfg["gate_min"], _tmp)
                    n = len(res["detections"])
                    txt = " | ".join(d[0] for d in res["detections"]) or "(tidak terdeteksi)"
                    print(f"t={t:.0f}s gate={res['gated']} {n} baris: {txt}", flush=True)

        def _on_save(_b):
            cfg = _cfg()
            path = os.path.join(WORK_DIR, "tuning_config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            globals()["ROI"] = cfg["roi"]
            globals()["MIN_CONF"] = cfg["min_conf"]
            globals()["UPSCALE"] = cfg["upscale"]
            globals()["MAX_WIDTH"] = cfg["max_width"]
            globals()["TEXT_GATE"] = cfg["text_gate"]
            globals()["TEXT_GATE_MIN_BRIGHT"] = cfg["gate_min"]
            with out:
                out.clear_output()
                print(f"Config disimpan ke {path} dan dipakai cell OCR berikutnya.")
                print("Supaya permanen, salin baris ini ke cell Konfigurasi:")
                print(f"ROI = {cfg['roi']}")
                print(f"MIN_CONF = {cfg['min_conf']}")
                print(f"UPSCALE = {cfg['upscale']}")
                print(f"MAX_WIDTH = {cfg['max_width']}")
                print(f"TEXT_GATE = {cfg['text_gate']}")
                print(f"TEXT_GATE_MIN_BRIGHT = {cfg['gate_min']}")

        btn_run.on_click(_on_run)
        btn_5.on_click(_on_5)
        btn_save.on_click(_on_save)
        display(widgets.VBox([
            w_video, w_time,
            widgets.HBox([w_roi_x0, w_roi_x1]),
            widgets.HBox([w_roi_y0, w_roi_y1]),
            widgets.HBox([w_conf, w_upscale, w_maxw]),
            widgets.HBox([w_gate, w_gate_min]),
            widgets.HBox([btn_run, btn_5, btn_save]),
            out,
        ]))
        print("[tune] atur slider, tekan 'Jalankan OCR'. "
              "Kotak merah = ROI, kotak hijau = hasil detect.", flush=True)
