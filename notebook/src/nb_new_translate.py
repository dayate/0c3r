import glob, json, os, re, time, urllib.error, urllib.request

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_mandarin(text):
    """True kalau teks masih berisi karakter Mandarin (belum diterjemah)."""
    return bool(text and _CJK_RE.search(text))


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


def llm_translate(lines):
    if not TIPROUTER_API_KEY:
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
                stats["llm"] += 1
            if n % 5 == 0:
                save_cache()
        save_cache()

    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if zh:
            cand = _cache.get(zh)
            # Jangan pernah menulis Mandarin ke text_id
            s["text_id"] = cand if (cand and not has_mandarin(cand)) else ""

    done = sum(1 for s in segs if s.get("text_id"))
    failed_final = []
    for s in segs:
        zh = (s.get("text_zh") or "").strip()
        if zh and not s.get("text_id"):
            failed_final.append({"start": s.get("start"), "end": s.get("end"),
                                 "text_zh": zh, "reason": "all_providers_failed"})
    print(f"  [tr] DeepL={stats['deepl']} Google={stats['google']} MyMemory={stats['mymemory']} "
          f"LLM={stats['llm']} gagal={len(failed_final)} | {done}/{len(segs)} segmen",
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
    missing = sum(1 for s in segs if (s.get("text_zh") or "").strip()
                  and not (s.get("text_id") or "").strip())
    if not missing and os.path.exists(out_id_srt):
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
    write_json_atomic(ep_json, payload)
    write_srt(segs, out_id_srt, "text_id")
    # Validator: tolak SRT yang tidak valid / masih berisi Mandarin
    assert_valid_segments(segs, where=f"translate {stem}")

print("[tr] selesai", flush=True)
