import glob, json, os, re, time, urllib.error, urllib.request

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_mandarin(text):
    """True kalau teks masih berisi karakter Mandarin (belum diterjemah)."""
    return bool(text and _CJK_RE.search(text))


# Validator + normalisasi SRT (cadangan): kalau cell 3b belum dijalankan
# di sesi ini — mis. runtime restart lalu cell Translate dijalankan
# langsung — definisi di bawah dipakai supaya cell tidak crash NameError.
# Isinya sama dengan notebook/src/nb_new_validate.py.
# Filter kartu nama juga didefinisikan di sini supaya ep_json lama (yang
# masih berisi kartu nama dari OCR sebelum filter) tetap dibersihkan.
def is_name_card(text, bbox):
    """True kalau segmen ini kartu nama/peran, bukan dialog (lihat OCR)."""
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


if "assert_valid_segments" not in globals() or "normalize_segments" not in globals():
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

    def _is_credit_line(text):
        """Kartu kredit (mis. '字幕by索兰娅') bukan dialog — buang.
        Pola sempit: kata '字幕' diikuti 'by' (nama pembuat subtitle)."""
        return "字幕by" in (text or "").lower().replace(" ", "")

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
            if _is_credit_line(s.get("text_zh") or ""):
                stats["dropped"] += 1
                continue
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
                elif txt_id and has_mandarin(txt_id):
                    errors.append(f"segmen {idx}: SRT ID masih berisi Mandarin")
        return errors

    def assert_valid_segments(segs, where=""):
        errors = validate_segments(segs)
        if errors:
            raise ValueError(f"validator SRT gagal {where}: " + "; ".join(errors[:10]))
        return True


# ========================= translate =========================
# Rantai (keputusan 2026-11-28): CipRouter API — step-3.7-flash dulu,
# gagal -> auto, gagal -> daftar review. Google DIHAPUS (D1: 0/41 dan
# 0/44 di Colab) dan NLLB DIHAPUS total (D3: kualitas drama jelek,
# load 291 dtk). Key dari Colab Secrets TIPROUTER_API_KEY — tidak pernah
# ditulis di notebook. Benchmark 44 baris: step 44/44 dalam 31,3 dtk,
# 0 reasoning token; auto 44/44 dalam 74,1 dtk (5.958 reasoning token).
_CIPROUTER_SYSTEM = (
    "Kamu penerjemah subtitle drama Mandarin ke bahasa Indonesia. "
    "Terjemahkan tiap baris ke bahasa Indonesia natural untuk subtitle, "
    "jaga nama orang (韩沐宸=Han Muchen, 温薏=Wen Yi) dan 闺蜜=sahabat. "
    "Jawab HANYA dengan daftar bernomor, satu terjemahan per baris, "
    "tanpa penjelasan."
)
_CIPROUTER_KEY_WARNED = False  # True sesudah peringatan key hilang dicetak sekali



if "_get_secret" not in globals():
    def _get_secret(name):
        """Baca secret dari Colab Secrets (userdata), fallback env var.
        Return None kalau tidak ada di keduanya."""
        try:
            from google.colab import userdata
            v = userdata.get(name)
            if v:
                return v
        except Exception:
            pass
        return os.environ.get(name) or None
def apply_name_overrides(text):
    """Ganti nama/istilah di teks ZH sebelum dikirim ke translator.
    Teks ZH yang disimpan (cache key + SRT ZH) TIDAK diubah — hanya salinan
    yang dikirim ke API. Return teks baru (atau teks asli kalau tidak ada
    yang cocok)."""
    for k, v in NAME_OVERRIDES.items():
        if k in text:
            text = text.replace(k, v)
    return text


def ciprouter_translate(lines, model):
    """Terjemah satu batch baris Mandarin -> Indonesia via CipRouter API.
    Return list 1:1 (urutan sama) atau None kalau gagal. Gagal di sini
    TIDAK menggagalkan episode — pemanggil mencoba model fallback, lalu
    menulis barisnya ke review."""
    global _CIPROUTER_KEY_WARNED
    key = _get_secret("TIPROUTER_API_KEY")
    if not key:
        if not _CIPROUTER_KEY_WARNED:
            print("  [tr] CipRouter: TIPROUTER_API_KEY tidak ada di Colab Secrets", flush=True)
            _CIPROUTER_KEY_WARNED = True
        return None
    lines = [apply_name_overrides(x) for x in lines]
    import urllib.error
    import urllib.request
    user = "Terjemahkan baris-baris ini:\n" + "\n".join(
        f"{n}. {s}" for n, s in enumerate(lines, 1))
    payload = {"model": model,
               "messages": [{"role": "system", "content": _CIPROUTER_SYSTEM},
                            {"role": "user", "content": user}],
               "temperature": 0}
    req = urllib.request.Request(
        CIPROUTER_URL, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=CIPROUTER_TIMEOUT) as r:
            resp = json.loads(r.read() or b"{}")
        content = resp["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [tr] CipRouter {model} gagal: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None
    # Parse daftar bernomor jadi list 1:1. Nomor di depan dibuang; baris
    # tanpa nomor tetap dihitung (model kadang menghilangkan nomor).
    # Baris pengantar ("Here is the translation...") membuat jumlah tidak
    # cocok -> return None -> fallback. Itu yang benar: jangan menebak.
    out = []
    for ln in content.strip().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"^\d+[.)]\s*(.*)$", ln)
        out.append(m.group(1).strip() if m else ln)
    if len(out) != len(lines):
        print(f"  [tr] CipRouter {model}: jumlah baris tidak cocok "
              f"({len(out)} vs {len(lines)})", flush=True)
        return None
    return [str(x).strip() for x in out]





def _clean_id(text):
    """Bersihkan hasil terjemah: buang tanda kutip yang membungkus seluruh
    baris (MyMemory sering mempertahankannya, mis. "Selamat ulang tahun")
    dan spasi ganda. Makna tidak diubah."""
    text = (text or "").strip()
    if len(text) >= 2 and text[0] in "\"“”'" and text[-1] in "\"“”'":
        text = text[1:-1].strip()
    return " ".join(text.split())


def translate_segments(segs):
    """step dulu (batch), gagal -> auto (batch), gagal -> auto per baris.
    Return (segs, failed_list).

    Jaminan: tidak ada baris yang dibiarkan Mandarin di text_id.
    Baris yang masih gagal setelah semua fallback dikembalikan di failed_list
    dan TIDAK ditulis ke SRT ID — pemanggil wajib menulis daftar review dan
    berhenti dengan status gagal yang jelas.
    """
    todo = []
    n_passthrough = 0
    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if not zh:
            s["text_id"] = ""
        elif zh in _cache:
            s["text_id"] = _cache[zh]
        elif not has_mandarin(zh):
            # Bukan dialog Mandarin (mis. sampah OCR latin / watermark):
            # tidak ada yang bisa diterjemah — teruskan apa adanya supaya
            # satu baris seperti ini tidak memblokir seluruh episode.
            _cache[zh] = zh
            _cache_prov[zh] = "passthrough"
            s["text_id"] = _clean_id(zh)
            n_passthrough += 1
        else:
            todo.append(zh)
    if n_passthrough:
        print(f"  [tr] {n_passthrough} baris non-Mandarin diteruskan apa adanya", flush=True)

    uniq = list(dict.fromkeys(todo))
    stats = {"step": 0, "auto": 0}

    def _batch_ok(chunk, out):
        return isinstance(out, list) and len(out) == len(chunk)

    def _simpan(chunk, out, prov):
        """Simpan baris yang valid dari satu batch. Return jumlah disimpan."""
        n = 0
        for zh, id_ in zip(chunk, out):
            if id_ and id_ != zh and not has_mandarin(id_):
                _cache[zh] = id_
                stats[prov] += 1
                _cache_prov[zh] = prov
                n += 1
        return n

    def _belum():
        return [zh for zh in uniq
                if zh not in _cache or has_mandarin(_cache.get(zh, zh))]

    # Rung 1: step, batch CIPROUTER_BATCH.
    for i in range(0, len(uniq), CIPROUTER_BATCH):
        chunk = uniq[i:i + CIPROUTER_BATCH]
        out = ciprouter_translate(chunk, CIPROUTER_MODEL_PRIMARY)
        if _batch_ok(chunk, out):
            _simpan(chunk, out, "step")
        print(f"  [tr] step {min(i + CIPROUTER_BATCH, len(uniq))}/{len(uniq)}", flush=True)
        save_cache()

    # Rung 2: auto, batch — hanya baris yang belum masuk cache.
    still = _belum()
    if still:
        print(f"  [tr] {len(still)} baris -> auto (fallback)", flush=True)
        for i in range(0, len(still), CIPROUTER_BATCH):
            chunk = still[i:i + CIPROUTER_BATCH]
            out = ciprouter_translate(chunk, CIPROUTER_MODEL_FALLBACK)
            if _batch_ok(chunk, out):
                _simpan(chunk, out, "auto")
            print(f"  [tr] auto {min(i + CIPROUTER_BATCH, len(still))}/{len(still)}", flush=True)
            save_cache()

    # Rung 3: retry per baris lewat auto.
    still = _belum()
    if still:
        print(f"  [tr] {len(still)} baris -> auto per baris (retry terakhir)", flush=True)
        for n, zh in enumerate(still, 1):
            out = ciprouter_translate([zh], CIPROUTER_MODEL_FALLBACK)
            if _batch_ok([zh], out):
                _simpan([zh], out, "auto")
            if n % 5 == 0:
                save_cache()
        save_cache()

    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if zh:
            cand = _cache.get(zh)
            # Jangan pernah menulis Mandarin ke text_id
            s["text_id"] = _clean_id(cand) if (cand and not has_mandarin(cand)) else ""

    done = sum(1 for s in segs if s.get("text_id"))
    failed_final = []
    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if zh and not s.get("text_id"):
            failed_final.append({"start": s.get("start"), "end": s.get("end"),
                                 "text_zh": zh, "reason": "all_providers_failed"})
    print(f"  [tr] step={stats['step']} auto={stats['auto']} "
          f"gagal={len(failed_final)} | {done}/{len(segs)} segmen", flush=True)
    return segs, failed_final


# ========================= tahap 2: Translate =========================
t_tr0 = time.time()
exts = (".mp4", ".mkv", ".webm", ".mov", ".avi")
videos = sorted([p for p in glob.glob(os.path.join(EPISODES_DIR, "*")) if p.lower().endswith(exts)],
                key=natural_key)[:MAX_EPISODES]
print(f"[tr] {len(videos)} episode (maks {MAX_EPISODES}) | cache {len(_cache)} entri", flush=True)

for i, vid_path in enumerate(videos, 1):
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    ep_json = os.path.join(PER_EP_DIR, f"{stem}_ocr.json")
    out_id_srt = os.path.join(PER_EP_DIR, f"{stem}_id.srt")
    if not os.path.exists(ep_json):
        print(f"[tr] {i}/{len(videos)} {stem}: skip (belum OCR)", flush=True)
        continue
    with open(ep_json, encoding="utf-8") as f:
        payload = json.load(f)
    segs = payload.get("segments", [])
    # Kartu nama/peran bukan dialog: buang sebelum dihitung/diterjemah.
    # Penting untuk ep_json lama yang masih berisi kartu dari OCR sebelum
    # filter ada — tanpa ini kartu ikut diterjemah dan dibakar jadi subtitle.
    segs, _n_cards = drop_name_cards(segs)
    if _n_cards:
        payload["segments"] = segs
        print(f"[tr] {i}/{len(videos)} {stem}: kartu nama dibuang: {_n_cards}", flush=True)
    missing = sum(1 for s in segs if (s.get("text_zh") or "").strip()
                  and not (s.get("text_id") or "").strip())
    if not missing and os.path.exists(out_id_srt):
        # Sudah diterjemah, tapi: kartu nama mungkin belum dibuang dan kutip
        # belum dibersihkan. Jalankan translate_segments: semua baris dari
        # cache, jadi tidak ada terjemahan ulang — hanya cleanup yang jalan.
        segs, failed_final = translate_segments(segs)
        payload["segments"] = segs
        if failed_final:
            review_path = os.path.join(PER_EP_DIR, f"{stem}_review.json")
            write_json_atomic(review_path, {"episode": stem, "failed": failed_final})
            print(f"[tr] {i}/{len(videos)} {stem}: GAGAL {len(failed_final)} baris, "
                  f"daftar review: {review_path}", flush=True)
            raise RuntimeError(
                f"translate gagal {len(failed_final)} baris di {stem} "
                f"(lihat {review_path})")
        # Rapikan dan tulis ulang kalau ada yang berubah — tanpa ini
        # cell akan skip dan SRT yang lama (overlap) tetap dipakai.
        segs, _nstats = normalize_segments(segs)
        if (_n_cards or _nstats["trimmed"] or _nstats["dropped"]
                or _nstats["wrapped"] or _nstats["split"]):
            payload["segments"] = segs
            write_json_atomic(ep_json, payload)
            write_srt(segs, out_id_srt, "text_id")
            print(f"[tr] {i}/{len(videos)} {stem}: dinormalisasi ulang "
                  f"dipotong={_nstats['trimmed']} dibuang={_nstats['dropped']} "
                  f"dibungkus={_nstats['wrapped']} dipecah={_nstats['split']}", flush=True)
        else:
            print(f"[tr] {i}/{len(videos)} {stem}: skip ({len(segs)} segmen sudah diterjemah)", flush=True)
        continue
    print(f"[tr] {i}/{len(videos)} {stem}: {len(segs)} segmen, {missing} baru", flush=True)
    segs, failed_final = translate_segments(segs)
    payload["segments"] = segs
    if failed_final:
        review_path = os.path.join(PER_EP_DIR, f"{stem}_review.json")
        write_json_atomic(review_path, {"episode": stem, "failed": failed_final})
        print(f"[tr] {i}/{len(videos)} {stem}: GAGAL {len(failed_final)} baris, "
              f"daftar review: {review_path}", flush=True)
        raise RuntimeError(
            f"translate gagal {len(failed_final)} baris di {stem} "
            f"(lihat {review_path}); perbaiki API key / koneksi lalu jalankan "
            f"cell ini lagi — hanya baris di daftar review yang dicoba ulang")
    # Normalisasi: rapikan overlap dari fusi Whisper + bungkus baris panjang
    # sebelum SRT ditulis dan divalidasi, supaya validator tidak menolak
    # masalah yang bisa diperbaiki otomatis.
    segs, _nstats = normalize_segments(segs)
    payload["segments"] = segs
    print(f"[tr] {i}/{len(videos)} {stem}: normalisasi "
          f"dipotong={_nstats['trimmed']} dibuang={_nstats['dropped']} "
          f"dibungkus={_nstats['wrapped']} dipecah={_nstats['split']}", flush=True)
    write_json_atomic(ep_json, payload)
    write_srt(segs, out_id_srt, "text_id")
    # Validator: tolak SRT yang tidak valid / masih berisi Mandarin
    assert_valid_segments(segs, where=f"translate {stem}")

print(f"[tr] selesai {time.time() - t_tr0:.1f} dtk", flush=True)
