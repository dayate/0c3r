"""Validator + normalisasi SRT / segmen Suba.

Dipakai setelah translate dan sebelum render: menolak hasil yang tidak
memenuhi aturan keterbacaan atau masih berisi Mandarin di SRT Indonesia.

Aturan (SPEC-MVP A5):
- start < end, timestamp monoton naik, tidak overlap dengan segmen berikut
- durasi tampil 0,2-7,0 detik (batas bawah 0,2: fusi Whisper bisa
  menghasilkan segmen pendek yang sah; 0,35 di OCR tetap berlaku di sana)
- maksimum 2 baris, maksimum 42 karakter per baris
- SRT ID: 0 baris berisi karakter Mandarin

`normalize_segments` memperbaiki masalah yang BISA diperbaiki sebelum
validator menolak: overlap antar segmen (biasa muncul dari fusi Whisper —
timing OCR digeser ke timing kata Whisper, dan segmen Whisper-only
disisipkan di antara segmen OCR), dan baris teks yang lebih dari 42
karakter (dibungkus di batas kata). Validator tetap menolak masalah
yang TIDAK bisa diperbaiki otomatis, mis. teks belum diterjemah.
"""
import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
MAX_CHARS_PER_LINE = 42
MIN_DUR = 0.2
MAX_DUR = 7.0


def has_mandarin(text):
    return bool(text and _CJK_RE.search(text))


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


def _wrap_text(text, max_len=MAX_CHARS_PER_LINE):
    """Bungkus teks di batas kata jadi baris-baris <= max_len karakter.
    Teks Mandarin tanpa spasi dibungkus per karakter."""
    text = (text or "").strip()
    if not text:
        return []
    lines, cur = [], ""
    for word in text.replace("\n", " ").split(" "):
        if not word:
            continue
        # Kata yang sendiri lebih panjang dari batas: potong per karakter
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
    """Rapikan segmen supaya lolos validator. Return (segs_baru, stats).

    - Urutkan berdasarkan start.
    - Potong end segmen yang overlap dengan segmen berikutnya
      (end = start berikutnya - 0,04). Segmen yang setelah dipotong
      durasinya < 0,2 detik dibuang (biasanya duplikat / fragmen).
    - Bungkus teks (text_zh dan text_id) ke maks 42 karakter/baris.
      Kalau setelah dibungkus masih > 2 baris, segmen dipecah jadi
      dua segmen dengan durasi dibagi dua.
    """
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
        # Bungkus teks dulu supaya panjang baris tidak mempengaruhi durasi
        for key in ("text_zh", "text_id"):
            txt = (s.get(key) or "").strip()
            if not txt:
                continue
            lines = _wrap_text(txt)
            if len(lines) != len(txt.split("\n")) or any(
                    len(l) > MAX_CHARS_PER_LINE for l in txt.split("\n")):
                stats["wrapped"] += 1
            s[key] = "\n".join(lines)
        # Pecah segmen yang teksnya tetap > 2 baris setelah dibungkus
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
    # Potong overlap: end segmen tidak boleh melewati start segmen berikut
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
        if end - start < MIN_DUR:
            stats["dropped"] += 1
            continue
        if end - start > MAX_DUR:
            s = dict(s)
            s["end"] = round(start + MAX_DUR, 3)
            stats["trimmed"] += 1
        fixed.append(s)
    return fixed, stats


def validate_segments(segs, check_id=True):
    """Return list error (string). Kosong = lolos."""
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
        dur = end - start
        if dur < MIN_DUR - 1e-6 or dur > MAX_DUR:
            errors.append(f"segmen {idx}: durasi {dur:.2f}s di luar batas wajar")
        for key in ("text_zh", "text_id"):
            txt = (s.get(key) or "").strip()
            if not txt:
                continue
            lines = txt.split("\n")
            if len(lines) > 2:
                errors.append(f"segmen {idx} ({key}): {len(lines)} baris, maks 2")
            for line in lines:
                if len(line) > MAX_CHARS_PER_LINE:
                    errors.append(f"segmen {idx} ({key}): baris {len(line)} karakter, maks {MAX_CHARS_PER_LINE}")
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
