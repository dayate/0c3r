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
                elif txt_id and has_mandarin(txt_id):
                    errors.append(f"segmen {idx}: SRT ID masih berisi Mandarin")
        return errors

    def assert_valid_segments(segs, where=""):
        errors = validate_segments(segs)
        if errors:
            raise ValueError(f"validator SRT gagal {where}: " + "; ".join(errors[:10]))
        return True


_deepl = None
_google = None
_mymemory = None

# ========================= translate =========================
def _strip_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt).rstrip("`").strip()
    i, j = txt.find("["), txt.rfind("]")
    return txt[i:j + 1] if i >= 0 and j > i else txt


def llm_translate(lines, system=None):
    if not TIPROUTER_API_KEY:
        return None
    system = system or ("Kamu penerjemah subtitle drama Mandarin ke bahasa Indonesia. "
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
                         "Authorization": "Bearer " + TIPROUTER_API_KEY})
            try:
                with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                out = json.loads(_strip_json(resp["choices"][0]["message"]["content"]))
                if isinstance(out, list) and len(out) == len(lines):
                    return [str(x).strip() for x in out]
                print(f"  [tr] LLM {model}: jumlah baris tidak cocok", flush=True)
            except urllib.error.HTTPError as e:
                print(f"  [tr] LLM {model} HTTP {e.code}", flush=True)
                if e.code in (429, 500, 502, 503):
                    time.sleep(2.0 * (attempt + 1))
                    continue
                break
            except Exception as e:
                print(f"  [tr] LLM {model} gagal: {type(e).__name__}: {str(e)[:120]}", flush=True)
                time.sleep(1.0)
    return None


def deepl_translate(text):
    global _deepl
    if not DEEPL_API_KEY:
        return None
    try:
        if _deepl is None:
            from deep_translator import DeepLTranslator
            _deepl = DeepLTranslator(api_key=DEEPL_API_KEY, source="zh", target="id")
        return _deepl.translate(text) or None
    except Exception as e:
        print(f"  [tr] DeepL: {str(e)[:100]}", flush=True)
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
        print(f"  [tr] gratis gagal: {str(e)[:100]}", flush=True)
    return None, None


def llm_translate_single(text):
    """Retry per baris lewat LLM, model kedua dulu, 2x percobaan per model.

    Dipakai hanya untuk baris yang gagal di semua jalur sebelumnya.
    Return teks Indonesia atau None.
    """
    out = llm_translate([text])
    if out and out[0] and out[0] != text and not has_mandarin(out[0]):
        return out[0]
    return None


def _clean_id(text):
    """Bersihkan hasil terjemah: buang tanda kutip yang membungkus seluruh
    baris (MyMemory sering mempertahankannya, mis. "Selamat ulang tahun")
    dan spasi ganda. Makna tidak diubah."""
    text = (text or "").strip()
    if len(text) >= 2 and text[0] in "\"“”'" and text[-1] in "\"“”'":
        text = text[1:-1].strip()
    return " ".join(text.split())


def llm_polish(lines):
    """Polish terjemahan Indonesia supaya natural seperti dialog drama.
    Dipakai hanya untuk baris dari MyMemory/Google. Return list atau None."""
    system = ("Kamu editor subtitle drama. Perbaiki terjemahan Indonesia ini "
              "supaya natural seperti dialog sehari-hari, jangan kaku, jangan "
              "ubah makna, jangan tambah atau buang informasi, jangan tambah "
              "tanda kutip. Balas HANYA JSON array of string, jumlah dan "
              "urutan sama dengan input.")
    return llm_translate(lines, system=system)


def translate_segments(segs):
    """Gratis dulu (DeepL -> Google -> MyMemory), sisa gagal baru LLM batch,
    lalu LLM per baris. Return (segs, failed_list).

    Jaminan: tidak ada baris yang dibiarkan Mandarin di text_id.
    Baris yang masih gagal setelah semua fallback dikembalikan di failed_list
    dan TIDAK ditulis ke SRT ID — pemanggil wajib menulis daftar review dan
    berhenti dengan status gagal yang jelas.
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
    stats = {"deepl": 0, "google": 0, "mymemory": 0, "llm": 0, "polish": 0}
    prov_of = {}
    failed = []
    for n, zh in enumerate(uniq, 1):
        out = deepl_translate(zh)
        if out and out != zh:
            _cache[zh] = out
            stats["deepl"] += 1
            prov_of[zh] = "deepl"
            _cache_prov[zh] = "deepl"
            continue
        out, prov = google_translate(zh)
        if out and out != zh:
            _cache[zh] = out
            stats[prov] += 1
            prov_of[zh] = prov
            _cache_prov[zh] = prov
        else:
            failed.append(zh)
        if n % 10 == 0:
            print(f"  [tr] gratis {n}/{len(uniq)} (gagal {len(failed)})", flush=True)
    save_cache()

    if failed:
        print(f"  [tr] {len(failed)} baris -> LLM fallback", flush=True)
        for i in range(0, len(failed), LLM_BATCH):
            chunk = failed[i:i + LLM_BATCH]
            out = llm_translate(chunk)
            if out:
                for zh, id_ in zip(chunk, out):
                    if id_ and id_ != zh and not has_mandarin(id_):
                        _cache[zh] = id_
                        stats["llm"] += 1
                        _cache_prov[zh] = "llm"
            print(f"  [tr] LLM {min(i + LLM_BATCH, len(failed))}/{len(failed)}", flush=True)
            save_cache()

    # Fallback terakhir: retry per baris lewat LLM (model kedua dulu di dalam
    # llm_translate). Baris yang lolos di sini masuk cache seperti biasa.
    still_failed = [zh for zh in failed
                    if zh not in _cache or has_mandarin(_cache.get(zh, zh))]
    if still_failed:
        print(f"  [tr] {len(still_failed)} baris -> LLM per baris (retry terakhir)", flush=True)
        for n, zh in enumerate(still_failed, 1):
            out = llm_translate_single(zh)
            if out:
                _cache[zh] = out
                _cache_prov[zh] = "llm"
                stats["llm"] += 1
            if n % 5 == 0:
                save_cache()
        save_cache()

    # Polish LLM: baris dari MyMemory/Google ditulis ulang supaya natural.
    # DeepL tidak ikut (kualitasnya sudah bagus), baris dari cache lama
    # (provider tidak tercatat) ikut sekali lalu ditandai "polished"
    # supaya tidak di-polish lagi di run berikutnya.
    if POLISH_WITH_LLM and TIPROUTER_API_KEY:
        all_zh = list(dict.fromkeys(
            (s.get("text_zh") or "").strip() for s in segs
            if (s.get("text_zh") or "").strip()))
        cands = [zh for zh in all_zh
                 if _cache_prov.get(zh) in (None, "mymemory", "google")
                 and _cache.get(zh) and not has_mandarin(_cache[zh])]
        if cands:
            print(f"  [tr] polish LLM {len(cands)} baris (MyMemory/Google/cache lama)", flush=True)
            for i in range(0, len(cands), LLM_BATCH):
                chunk = cands[i:i + LLM_BATCH]
                out = llm_polish([_cache[zh] for zh in chunk])
                if out:
                    for zh, id_ in zip(chunk, out):
                        old = _cache[zh]
                        if (id_ and id_ != old and not has_mandarin(id_)
                                and 0.5 * len(old) <= len(id_) <= 2.0 * len(old)):
                            _cache[zh] = _clean_id(id_)
                            _cache_prov[zh] = "polished"
                            stats["polish"] += 1
                print(f"  [tr] polish {min(i + LLM_BATCH, len(cands))}/{len(cands)}", flush=True)
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
    print(f"  [tr] DeepL={stats['deepl']} Google={stats['google']} MyMemory={stats['mymemory']} "
          f"LLM={stats['llm']} polish={stats['polish']} gagal={len(failed_final)} | {done}/{len(segs)} segmen",
          flush=True)
    return segs, failed_final


# ========================= tahap 2: Translate =========================
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
        # Sudah diterjemah, tapi: kartu nama mungkin belum dibuang, baris
        # MyMemory/Google/cache lama belum di-polish, kutip belum dibersihkan.
        # Jalankan translate_segments: semua baris dari cache, jadi tidak ada
        # terjemahan ulang — hanya polish + cleanup yang jalan.
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

print("[tr] selesai", flush=True)
