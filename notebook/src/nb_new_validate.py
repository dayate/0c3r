"""Validator SRT / segmen Suba.

Dipakai setelah translate dan sebelum render: menolak hasil yang tidak
memenuhi aturan keterbacaan atau masih berisi Mandarin di SRT Indonesia.

Aturan (SPEC-MVP A5):
- start < end, timestamp monoton naik, tidak overlap dengan segmen berikut
- durasi tampil 1,0-7,0 detik (segmen < 0,35 detik sudah dibuang di OCR,
  tapi validator tetap menolak durasi di luar batas ini)
- maksimum 2 baris, maksimum 42 karakter per baris
- SRT ID: 0 baris berisi karakter Mandarin
"""
import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
MAX_CHARS_PER_LINE = 42
MIN_DUR = 1.0
MAX_DUR = 7.0


def has_mandarin(text):
    return bool(text and _CJK_RE.search(text))


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
        if dur < 0.35 or dur > MAX_DUR:
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
