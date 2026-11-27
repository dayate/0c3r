import glob, json, os, subprocess, time
import re as _re

# Validator SRT (cadangan): kalau cell 3b belum dijalankan di sesi ini,
# definisi di bawah dipakai supaya cell tidak crash NameError.
# Isinya sama dengan notebook/src/nb_new_validate.py.
if "assert_valid_segments" not in globals():
    _CJK_RE = _re.compile(r"[\u4e00-\u9fff]")

    def _has_mandarin(text):
        return bool(text and _CJK_RE.search(text))

    def _wrap_text(text, max_len=42):
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
        """Rapikan segmen: potong overlap, bungkus baris > 42 char,
        pecah segmen yang teksnya tetap > 2 baris. Return (segs, stats)."""
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
                elif txt_id and _has_mandarin(txt_id):
                    errors.append(f"segmen {idx}: SRT ID masih berisi Mandarin")
        return errors

    def assert_valid_segments(segs, where=""):
        errors = validate_segments(segs)
        if errors:
            raise ValueError(f"validator SRT gagal {where}: " + "; ".join(errors[:10]))
        return True

# ========================= ffmpeg progress =========================
def run_ffmpeg(cmd, dur, tag):
    """Jalankan ffmpeg (cmd sudah termasuk output), print progress tiap PROGRESS_PCT%."""
    full = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    t0 = time.time()
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
            print(f"  [{tag}] {min(100, int(sec * 100 / dur))}% ({sec:.1f}s)", flush=True)
            nxt += step
    err = (p.stderr.read() or "").strip()
    p.wait()
    return p.returncode, err, time.time() - t0


# ========================= band & blur =========================
def _pct(vals, q):
    v = sorted(vals)
    if len(v) == 1:
        return v[0]
    i = (len(v) - 1) * q / 100.0
    lo, hi = int(i), min(int(i) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def compute_band(segs, vh):
    """Band blur dari bbox teks, tahan outlier OCR.
    Outlier (box sempit/tinggi karena deteksi rusak) dibuang, lalu y dipotong
    p10-p90 supaya tidak melebar ke konten atas/bawah. x tetap full extent."""
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
    """Return (filter_complex_prefix, label_output).
    static: satu rect fixed; ALWAYS_BLUR=True -> overlay selalu nyala (OCR miss aman),
    False -> hanya pada window tiap segmen. dynamic: rect per segmen (paling presisi)."""
    def blur(h):
        r = max(2, min(BLUR_RADIUS, h // 2 - 1))
        return (f"boxblur=luma_radius={r}:luma_power=2:"
                f"chroma_radius={max(1, r // 2)}:chroma_power=1")

    if mode == "dynamic":
        chain, cur = [], "[0:v]"
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


# ========================= ASS subtitle =========================
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


# ========================= tahap 3: Blur + Burn =========================
def render_hardsub(vid_path, out_mp4, segs, vw, vh, mode=None):
    mode = mode or BLUR_MODE
    use_nvenc = has_nvenc()
    dur = probe(vid_path)[0]
    band = compute_band(segs, vh)
    print(f"  [blur] band={tuple(round(v, 3) for v in band) if band else None} mode={mode} "
          f"segmen={sum(1 for s in segs if s.get('bbox'))} radius={BLUR_RADIUS} "
          f"always={ALWAYS_BLUR}", flush=True)

    font_size = max(20, round(vw * 0.042))
    if band:
        center_y = (band[1] + band[3]) / 2
        margin_v = max(8, int(round((1 - center_y) * vh - font_size * 0.55)))
    else:
        margin_v = int(vh * 0.06)

    ass_path = os.path.join(WORK_DIR, os.path.splitext(os.path.basename(out_mp4))[0] + ".ass")
    write_ass(segs, ass_path, vw, vh, font_size, margin_v)
    nsub = sum(1 for s in segs if (s.get("text_id") or "").strip())
    print(f"  [sub] {nsub} baris font={font_size} margin_v={margin_v}", flush=True)
    sub = f"ass=filename='{_sub_path(ass_path)}'"

    blur_prefix, bg_label = build_blur(segs, band, vw, vh, mode) if band else (None, None)
    if blur_prefix and bg_label:
        fc = f"{blur_prefix};{bg_label}{sub}[v]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-filter_complex", fc,
               "-map", "[v]", "-map", "0:a?", "-c:a", "copy"]
    elif band:
        print("  [blur] build_blur gagal, fallback tanpa blur", flush=True)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-vf", sub, "-map", "0:v:0",
               "-map", "0:a?", "-c:a", "copy"]
    else:
        print("  [blur] tidak ada bbox teks, blur dilewati", flush=True)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-vf", sub, "-map", "0:v:0",
               "-map", "0:a?", "-c:a", "copy"]

    variants = []
    if use_nvenc:
        variants.append(["-c:v", "h264_nvenc", "-preset", "p6", "-cq", "24"])
    variants.append(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])

    for enc in variants:
        full = cmd + enc + ["-movflags", "+faststart", out_mp4]
        print(f"  [render] enc={enc[1]}", flush=True)
        rc, err, t_enc = run_ffmpeg(full, dur, "render")
        if rc == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 0:
            print(f"  [render] OK {t_enc:.1f}s ({os.path.getsize(out_mp4) / 1048576:.1f} MB)",
                  flush=True)
            return enc[1], t_enc
        print(f"  [render] {enc[1]} gagal: {err[-300:]}", flush=True)
        if os.path.exists(out_mp4):
            os.remove(out_mp4)
    raise RuntimeError("semua encoder gagal")


exts = (".mp4", ".mkv", ".webm", ".mov", ".avi")
videos = sorted([p for p in glob.glob(os.path.join(EPISODES_DIR, "*")) if p.lower().endswith(exts)],
                key=natural_key)[:MAX_EPISODES]
print(f"[render] {len(videos)} episode (maks {MAX_EPISODES})", flush=True)

t_all = time.time()
for i, vid_path in enumerate(videos, 1):
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    ep_json = os.path.join(PER_EP_DIR, f"{stem}_ocr.json")
    out_hard_mp4 = os.path.join(HARDSUB_EP_DIR, f"{stem}_id_hardsub.mp4")
    if not os.path.exists(ep_json):
        print(f"[render] {i}/{len(videos)} {stem}: skip (belum OCR)", flush=True)
        continue
    if os.path.exists(out_hard_mp4):
        print(f"[render] {i}/{len(videos)} {stem}: skip (hardsub ada)", flush=True)
        continue
    with open(ep_json, encoding="utf-8") as f:
        payload = json.load(f)
    segs = payload.get("segments", [])
    # Normalisasi dulu (rapikan overlap / baris panjang), baru validasi.
    # Jangan bakar video dari SRT yang tidak valid / belum diterjemah penuh.
    if "normalize_segments" in globals():
        segs, _nstats = normalize_segments(segs)
    assert_valid_segments(segs, where=f"render {stem}")
    dur, vw, vh = probe(vid_path)
    print(f"[render] {i}/{len(videos)} {stem} | {dur:.1f}s {vw}x{vh} {len(segs)} segmen", flush=True)
    enc, t_render = render_hardsub(vid_path, out_hard_mp4, segs, vw, vh)
    print(f"[render] {i}/{len(videos)} {stem}: OK enc={enc} {t_render:.1f}s", flush=True)

print(f"[render] selesai dalam {(time.time() - t_all) / 60:.1f} menit", flush=True)
