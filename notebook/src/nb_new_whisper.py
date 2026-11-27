"""Cell 4b — Whisper timing + fusi (terpisah dari OCR).

Tujuan: timing yang pas dan tidak miss timing.
OCR 1 fps memberi timing +-1 detik dan bisa melewatkan baris pendek.
Whisper memberi timing kata yang jauh lebih rapat.

Aturan (audio dan hardsub sama-sama Mandarin):
- Teks pakai OCR, timing pakai Whisper.
- Baris yang hanya ada di Whisper ditambahkan, ditandai source="asr".
- Baris yang hanya ada di OCR dipertahankan, ditandai source="ocr".
- Kalau teks OCR dan Whisper berbeda jauh di waktu yang sama,
  segmen ditandai conflict=True, teks OCR tetap dipakai, masuk review.
- Cell ini boleh dilewati: kalau dilewati, timing tetap memakai OCR.

Setting Whisper (metode cepat 2026-11-27):
  model "small" (default dari cell config), compute_type float16 di GPU
  (fallback int8 di CPU), language="zh" dikunci, vad_filter=False,
  condition_on_previous_text=False, temperature=0.0, beam_size=1 (greedy),
  word_timestamps=True.
  Whisper HANYA dipakai buat timing + cadangan, teks tetap dari OCR —
  jadi model kecil sudah cukup (4-6x lebih cepat dari large-v3-turbo
  di CPU). large-v3-turbo tetap tersedia lewat WHISPER_MODEL di config
  kalau butuh akurasi penuh.
  Di Colab cell ini jalan setelah cell OCR (berurutan); paralel
  OCR+Whisper hanya di pipeline lokal (ThreadPoolExecutor) — di GPU
  Whisper sudah cepat jadi antrean ini tidak terasa.
"""
import difflib
import glob
import json
import os
import re
import shutil
import subprocess
import time
import wave

import numpy as np

# Nilai dari cell config kalau ada; default di sini supaya cell ini tetap
# bisa jalan sendiri (mis. sesi baru yang cell confignya belum diubah).
WHISPER_MODEL = globals().get("WHISPER_MODEL", "small")
WHISPER_BEAM = globals().get("WHISPER_BEAM", 1)
WHISPER_LANG = globals().get("WHISPER_LANG", "zh")
WHISPER_MAX_SHIFT = 1.5  # detik, batas geser timing OCR ke timing Whisper


# Util (didupikasi dari cell OCR supaya cell ini bisa jalan sendiri)
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


def _whisper_fingerprint():
    return {
        "profile": globals().get("PROFILE", "colab"),
        "model": WHISPER_MODEL,
        "lang": WHISPER_LANG,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "temperature": 0.0,
        "beam_size": WHISPER_BEAM,
        "word_timestamps": True,
        "chunk_seconds": CHUNK_SECONDS,
    }


def _extract_audio(vid_path, wav_path):
    if os.path.exists(wav_path):
        return wav_path
    os.makedirs(os.path.dirname(wav_path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", vid_path, "-vn", "-ac", "1",
         "-ar", "16000", wav_path],
        check=True, capture_output=True)
    return wav_path


_cpu_model = None  # diisi saat fallback CPU karena libcublas hilang


def _preload_cublas():
    """Preload libcublas.so.12 dari paket nvidia-cublas-cu12 (kalau ada).

    Di Colab, faster-whisper/ctranslate2 butuh libcublas.so.12 saat encode
    di GPU, tapi library itu tidak selalu ada di image Colab. Kalau tidak
    di-preload, encode gagal: "Library libcublas.so.12 is not found".
    """
    try:
        import ctypes
        import glob as _glob
        import sysconfig
        base = sysconfig.get_paths().get("purelib", "")
        for pat in (os.path.join(base, "nvidia", "cublas", "lib", "libcublas.so.12"),
                    os.path.join(base, "nvidia", "cudnn", "lib", "libcudnn.so.9"),
                    "/usr/local/cuda/lib64/libcublas.so.12"):
            for path in _glob.glob(pat):
                try:
                    ctypes.CDLL(path)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _get_model(force_cpu=False):
    _preload_cublas()
    from faster_whisper import WhisperModel
    if force_cpu:
        print("  [whisper] pakai CPU int8 (fallback libcublas)", flush=True)
        return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    try:
        import torch
        has_cuda = bool(torch.cuda.is_available())
    except Exception:
        has_cuda = False
    if has_cuda:
        return WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
    print("  [whisper] GPU tidak tersedia, fallback CPU int8 (lebih lambat)", flush=True)
    return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")


def _load_wav_array(path):
    """Baca WAV ke float32 ndarray (mono, -1.0..1.0).

    Jangan serahkan path WAV ke faster-whisper: versi 1.2.1 + PyAV 19
    crash di decode_audio -> av.open(..., metadata_errors="ignore")
    karena PyAV 19 tidak lagi menerima argumen itu. Membaca WAV
    langsung dengan stdlib wave + numpy melewati jalur itu.
    """
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    if sampwidth == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"sampwidth WAV tidak didukung: {sampwidth}")
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    return np.ascontiguousarray(audio, dtype=np.float32)


def _transcribe_chunk(model, wav_path, start, dur):
    """Transkrip satu chunk audio, timestamp di-offset ke waktu video.

    Kalau encode GPU gagal karena libcublas.so.12 tidak ditemukan,
    otomatis ganti ke model CPU int8 dan coba sekali lagi — cell tidak
    crash, cuma lebih lambat. Model CPU dipakai untuk chunk berikutnya.
    """
    global _cpu_model
    if _cpu_model is not None:
        model = _cpu_model
    tmp = wav_path + f".chunk{int(start)}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
         "-i", wav_path, tmp],
        check=True, capture_output=True)
    try:
        audio = _load_wav_array(tmp)
        try:
            segments, _info = model.transcribe(
                audio, language=WHISPER_LANG, vad_filter=False,
                condition_on_previous_text=False, temperature=0.0,
                beam_size=WHISPER_BEAM, word_timestamps=True)
        except RuntimeError as e:
            if "cublas" not in str(e).lower() and "libcublas" not in str(e).lower():
                raise
            print("  [whisper] libcublas.so.12 tidak ditemukan di GPU, "
                  "fallback ke CPU int8 (lebih lambat, tapi jalan)", flush=True)
            _cpu_model = _get_model(force_cpu=True)
            segments, _info = _cpu_model.transcribe(
                audio, language=WHISPER_LANG, vad_filter=False,
                condition_on_previous_text=False, temperature=0.0,
                beam_size=WHISPER_BEAM, word_timestamps=True)
        out = []
        for seg in segments:
            words = []
            for w in (seg.words or []):
                words.append({"start": round(start + float(w.start), 3),
                              "end": round(start + float(w.end), 3),
                              "word": str(w.word).strip()})
            out.append({
                "start": round(start + float(seg.start), 3),
                "end": round(start + float(seg.end), 3),
                "text": str(seg.text).strip(),
                "words": words,
                "avg_logprob": float(getattr(seg, "avg_logprob", 0.0) or 0.0),
            })
        return out
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _overlap(a_start, a_end, b_start, b_end):
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _similarity(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def fuse_segments(ocr_segs, whisper_segs):
    """Gabung OCR + Whisper. Return (fused, stats)."""
    fused = []
    used_whisper = set()
    stats = {"timing_fixed": 0, "whisper_only": 0, "conflict": 0, "ocr_only": 0}

    for o in ocr_segs:
        o_start, o_end = float(o["start"]), float(o["end"])
        overlapping = []
        for wi, w in enumerate(whisper_segs):
            if _overlap(o_start, o_end, float(w["start"]), float(w["end"])) > 0:
                overlapping.append((wi, w))
        if not overlapping:
            fused.append({**o, "source": "ocr", "conflict": False,
                          "timing_unverified": True})
            stats["ocr_only"] += 1
            continue
        for wi, _w in overlapping:
            used_whisper.add(wi)
        # Timing dari word timestamp Whisper di dalam overlap
        word_times = []
        whisper_texts = []
        for _wi, w in overlapping:
            whisper_texts.append(w.get("text", ""))
            for wd in (w.get("words") or []):
                if _overlap(o_start, o_end, wd["start"], wd["end"]) > 0:
                    word_times.append((wd["start"], wd["end"]))
        new_start, new_end = o_start, o_end
        if word_times:
            ws = min(t[0] for t in word_times)
            we = max(t[1] for t in word_times)
            # Batas geser supaya satu kesalahan Whisper tidak merusak timing
            new_start = max(o_start - WHISPER_MAX_SHIFT, min(o_start + WHISPER_MAX_SHIFT, ws))
            new_end = max(o_end - WHISPER_MAX_SHIFT, min(o_end + WHISPER_MAX_SHIFT, we))
            if new_end - new_start < 0.35:
                new_end = new_start + 0.35
            if abs(new_start - o_start) > 0.05 or abs(new_end - o_end) > 0.05:
                stats["timing_fixed"] += 1
        whisper_text = " ".join(whisper_texts).strip()
        conflict = False
        if whisper_text and _similarity(o.get("text_zh", ""), whisper_text) < 0.5:
            conflict = True
            stats["conflict"] += 1
        fused.append({**o, "start": round(new_start, 3), "end": round(new_end, 3),
                      "source": "ocr", "conflict": conflict,
                      "timing_unverified": False})

    for wi, w in enumerate(whisper_segs):
        if wi in used_whisper:
            continue
        if float(w["end"]) - float(w["start"]) < 0.35:
            continue
        if not (w.get("text") or "").strip():
            continue
        fused.append({"start": float(w["start"]), "end": float(w["end"]),
                      "text_zh": w["text"].strip(), "bbox": None,
                      "source": "asr", "conflict": False,
                      "timing_unverified": False})
        stats["whisper_only"] += 1

    fused.sort(key=lambda s: (float(s["start"]), float(s["end"])))
    return fused, stats


# ========================= tahap 4b: Whisper =========================
exts = (".mp4", ".mkv", ".webm", ".mov", ".avi")
videos = sorted([p for p in glob.glob(os.path.join(EPISODES_DIR, "*")) if p.lower().endswith(exts)],
                key=natural_key)[:MAX_EPISODES]
print(f"[whisper] {len(videos)} episode (maks {MAX_EPISODES}) | model {WHISPER_MODEL}", flush=True)

model = None
for i, vid_path in enumerate(videos, 1):
    stem = os.path.splitext(os.path.basename(vid_path))[0]
    ep_json = os.path.join(PER_EP_DIR, f"{stem}_ocr.json")
    whisper_json = os.path.join(PER_EP_DIR, f"{stem}_whisper.json")
    if not os.path.exists(ep_json):
        print(f"[whisper] {i}/{len(videos)} {stem}: skip (belum OCR)", flush=True)
        continue
    with open(ep_json, encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("whisper_applied") and payload.get("whisper_fingerprint") == _whisper_fingerprint():
        print(f"[whisper] {i}/{len(videos)} {stem}: skip (fusi sudah ada)", flush=True)
        continue
    ocr_segs = payload.get("segments", [])
    dur, vw, vh = probe(vid_path)
    print(f"[whisper] {i}/{len(videos)} {stem} | {dur:.1f}s {len(ocr_segs)} segmen OCR", flush=True)

    if model is None:
        model = _get_model()
    wav_path = os.path.join(WORK_DIR, "audio", stem + ".wav")
    _extract_audio(vid_path, wav_path)

    # Transkrip per chunk, checkpoint per chunk
    cdir = os.path.join(WORK_DIR, "chunks", stem)
    os.makedirs(cdir, exist_ok=True)
    fp = _whisper_fingerprint()
    whisper_segs = []
    starts, s = [], 0.0
    while s < max(dur, 0.1):
        starts.append(s)
        s += CHUNK_SECONDS
    for start in starts:
        cend = min(start + CHUNK_SECONDS, dur if dur > 0 else start + CHUNK_SECONDS)
        cpath = os.path.join(cdir, f"whisper_chunk_{int(start):06d}.json")
        data = None
        if os.path.exists(cpath):
            try:
                with open(cpath, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("fingerprint") != fp:
                    data = None
            except Exception:
                data = None
        if data is None:
            got = _transcribe_chunk(model, wav_path, start, cend - start)
            write_json_atomic(cpath, {"start": start, "end": cend,
                                      "fingerprint": fp, "segments": got})
            whisper_segs.extend(got)
        else:
            whisper_segs.extend(data.get("segments", []))
    whisper_segs.sort(key=lambda x: float(x["start"]))

    fused, stats = fuse_segments(ocr_segs, whisper_segs)
    # Fusi bisa menimbulkan overlap (timing OCR digeser ke timing kata
    # Whisper + segmen Whisper-only disisipkan). Rapikan di sini kalau
    # normalisasi tersedia; kalau tidak (mis. cell 3b lama yang jalan),
    # potong overlap secara sederhana — cell Translate tetap menormalisasi
    # lagi sebelum menulis SRT ID, jadi ini bukan satu-satunya pengaman.
    if "normalize_segments" in globals():
        fused, _nstats = normalize_segments(fused)
        print(f"[whisper] {i}/{len(videos)} {stem}: normalisasi "
              f"dipotong={_nstats['trimmed']} dibuang={_nstats['dropped']} "
              f"dibungkus={_nstats['wrapped']} dipecah={_nstats['split']}", flush=True)
    else:
        _trimmed = 0
        for _i in range(len(fused) - 1):
            if float(fused[_i]["end"]) > float(fused[_i + 1]["start"]) - 0.04:
                fused[_i] = dict(fused[_i])
                fused[_i]["end"] = round(float(fused[_i + 1]["start"]) - 0.04, 3)
                _trimmed += 1
        if _trimmed:
            print(f"[whisper] {i}/{len(videos)} {stem}: potong overlap sederhana {_trimmed}",
                  flush=True)
    payload["segments"] = fused
    payload["whisper_applied"] = True
    payload["whisper_fingerprint"] = fp
    write_json_atomic(ep_json, payload)
    write_json_atomic(whisper_json, {"episode": stem, "model": WHISPER_MODEL,
                                     "segments": whisper_segs})
    write_srt(fused, os.path.join(PER_EP_DIR, f"{stem}_zh.srt"), "text_zh")
    print(f"[whisper] {i}/{len(videos)} {stem}: timing diperbaiki {stats['timing_fixed']}, "
          f"whisper-only {stats['whisper_only']}, konflik {stats['conflict']}, "
          f"ocr-only {stats['ocr_only']}", flush=True)

print("[whisper] selesai", flush=True)
