"""Smoke test: render 4s video dengan blur always-on + progress + ASS."""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_pipeline as lp

lp.setup_logging()
td = tempfile.mkdtemp()
src = os.path.join(td, "in.mp4")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24",
                "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", src], check=True)

segs = [
    {"start": 0.5, "end": 1.5, "text_zh": "你好", "text_id": "Halo", "bbox": [0.2, 0.66, 0.8, 0.72]},
    {"start": 2.0, "end": 3.0, "text_zh": "再见", "text_id": "Sampai jumpa", "bbox": [0.25, 0.67, 0.75, 0.73]},
]
out = os.path.join(td, "out.mp4")
enc, t = lp.render_hardsub(src, "", out, segs, 640, 360)
assert os.path.getsize(out) > 0
print("SMOKE OK", enc, round(t, 2), "s", os.path.getsize(out), "bytes")

# --- render yang dibatalkan meninggalkan mp4 puluhan byte: jangan dianggap selesai ---
_bad = os.path.join(td, "bad.mp4")
with open(_bad, "wb") as _f:
    _f.write(b"\x00" * 48)
assert not lp._hardsub_ok(_bad), "mp4 rusak tidak boleh dianggap selesai"
assert lp._hardsub_ok(out), "mp4 valid harus dianggap selesai"
print("HARDSUB VALID OK")

# filter statis harus tanpa enable= saat ALWAYS_BLUR
band = lp.compute_band(segs, 360)
fc, _ = lp.build_blur(segs, band, 640, 360, "static")
assert "enable=" not in fc, fc
lp.ALWAYS_BLUR = False
fc2, _ = lp.build_blur(segs, band, 640, 360, "static")
assert "enable=" in fc2
print("FILTER OK")

# --- translate: gratis saja (DeepL -> Google -> MyMemory), tanpa LLM ---
lp.TR_CACHE_PATH = os.path.join(td, "cache.json")
lp._cache.clear()
calls = []

def fake_free(t):
    calls.append(t)
    return ({"你好": "Halo", "再见": "Sampai jumpa"}.get(t, "Terjemahan"), "google")

lp.deepl_translate = lambda t: None
lp.google_translate = fake_free
segs2 = [{"text_zh": "你好"}, {"text_zh": "再见"}, {"text_zh": "你好"}]
segs2, failed2 = lp.translate_segments(segs2)
assert failed2 == [], failed2
assert calls == ["你好", "再见"], calls
assert segs2[0]["text_id"] == "Halo" and segs2[2]["text_id"] == "Halo"
print("TRANSLATE OK")

# --- translate: gagal di semua jalur gratis -> masuk daftar gagal, text_id kosong ---
lp._cache.clear()
lp.google_translate = lambda t: (None, None)
segs4 = [{"text_zh": "你好"}]
segs4, failed4 = lp.translate_segments(segs4)
assert len(failed4) == 1 and failed4[0]["text_zh"] == "你好", failed4
assert segs4[0]["text_id"] == "", segs4
assert lp.validate_segments(segs4), "validator harus menolak baris belum diterjemah"
assert not hasattr(lp, "llm_translate"), "versi lokal tidak boleh punya jalur LLM"
print("TRANSLATE FAIL OK")

# --- translate: baris non-Mandarin diteruskan apa adanya, provider tidak dipanggil ---
lp._cache.clear()
lp._cache_prov.clear()
calls_p = []

def _deepl_rec(t):
    calls_p.append(t)
    return None

lp.deepl_translate = _deepl_rec
lp.google_translate = lambda t: (None, None)
segs_p = [{"text_zh": "ALSURR 120."}, {"text_zh": "你好"}]
segs_p, failed_p = lp.translate_segments(segs_p)
assert len(failed_p) == 1 and failed_p[0]["text_zh"] == "你好", failed_p
assert segs_p[0]["text_id"] == "ALSURR 120.", segs_p
assert lp._cache_prov.get("ALSURR 120.") == "passthrough"
assert calls_p == ["你好"], calls_p
print("TRANSLATE PASSTHROUGH OK")

# --- validator SRT ---
good = [{"start": 0.5, "end": 1.5, "text_zh": "你好", "text_id": "Halo"},
        {"start": 2.0, "end": 3.0, "text_zh": "再见", "text_id": "Sampai jumpa"}]
assert lp.validate_segments(good) == [], lp.validate_segments(good)
bad_overlap = [{"start": 0.5, "end": 2.5, "text_zh": "你好", "text_id": "Halo"},
               {"start": 2.0, "end": 3.0, "text_zh": "再见", "text_id": "Sampai jumpa"}]
assert lp.validate_segments(bad_overlap), "validator harus menolak overlap"
bad_mandarin = [{"start": 0.5, "end": 1.5, "text_zh": "你好", "text_id": "你好"}]
assert lp.validate_segments(bad_mandarin), "validator harus menolak Mandarin di SRT ID"
print("VALIDATOR OK")

# Normalisasi: kasus nyata dari Colab 2026-11-27 — overlap dari fusi Whisper,
# durasi 0.35s, dan baris ID 44/46 karakter. Sebelum normalisasi validator
# menolak, sesudahnya harus lolos.
bad = [
    {"start": 2.0, "end": 4.42, "text_zh": "你好吗", "text_id": "Apa kabar kamu hari ini"},
    {"start": 3.64, "end": 5.1, "text_zh": "很好", "text_id": "Aku baik-baik saja, terima kasih"},
    {"start": 4.84, "end": 5.19, "text_zh": "谢谢", "text_id": "Terima kasih banyak ya"},
    {"start": 6.0, "end": 6.35, "text_zh": "再见", "text_id": "Sampai jumpa lagi nanti ya"},
    {"start": 10.0, "end": 12.0, "text_zh": "我想去看看那个地方", "text_id": "Aku ingin pergi melihat tempat itu besok pagi"},
]
assert lp.validate_segments(bad), "kasus nyata harus ditolak sebelum normalisasi"
fixed, nstats = lp.normalize_segments(bad)
assert lp.validate_segments(fixed) == [], lp.validate_segments(fixed)
assert all(len(l) <= 42 for s in fixed for l in (s["text_id"] or "").split("\n"))
assert nstats["trimmed"] >= 2 and nstats["wrapped"] >= 1, nstats
print("NORMALIZE OK", nstats)

# --- kartu nama/peran bukan dialog ---
card = {"start": 119.0, "end": 121.0, "text_zh": "丰宸集团总裁",
        "bbox": [0.05, 0.50, 0.12, 0.65]}
assert lp.is_name_card(card["text_zh"], card["bbox"]), "kartu jabatan vertikal harus dikenali"
assert lp.is_name_card("韩沐宸", [0.05, 0.50, 0.10, 0.62]), "nama vertikal pendek harus dikenali"
assert not lp.is_name_card("你好吗", [0.2, 0.66, 0.8, 0.72]), "dialog horizontal jangan ikut terbuang"
assert not lp.is_name_card("我是他的助理", [0.2, 0.66, 0.8, 0.72]), "dialog berisi kata jabatan tapi horizontal jangan dibuang"
kept, n_cards = lp.drop_name_cards([card, good[0]])
assert n_cards == 1 and len(kept) == 1, (n_cards, kept)
print("NAME CARD OK")

# --- blur dynamic: jendela ber-padding, radius/power baru, segmen tanpa bbox pakai band ---
# (radius config 20, tapi dibatasi setengah tinggi crop: 32px -> 15)
assert lp.BLUR_RADIUS == 20
lp.ALWAYS_BLUR = True
fc_dyn, _ = lp.build_blur(segs, band, 640, 360, "dynamic")
# gblur (bukan boxblur lagi): h=32 -> sigma 7.5
assert "gblur=sigma=7.5" in fc_dyn and "boxblur" not in fc_dyn, fc_dyn
assert "between(t,0.100,1.900)" in fc_dyn, fc_dyn  # 0.5-0.4 s/d 1.5+0.4 s
no_bbox = [{"start": 0.5, "end": 1.5, "text_zh": "你好", "text_id": "Halo"}]
fc_nb, _ = lp.build_blur(no_bbox, band, 640, 360, "dynamic")
assert fc_nb is not None and "between(t,0.100,1.900)" in fc_nb, fc_nb
print("BLUR DYNAMIC OK")

# --- guard: dynamic dipaksa static kalau baris banyak (2026-11-28) ---
_many = [{"start": 0, "end": 1, "text_zh": "x"} for _ in range(lp.DYNAMIC_MAX_BOX + 1)]
assert lp._blur_mode_for(_many, "dynamic") == "static"
assert lp._blur_mode_for(_many[:-1], "dynamic") == "dynamic"
assert lp._blur_mode_for(_many, "static") == "static"
print("BLUR GUARD OK")

# --- translate: kutip dibersihkan, tanpa polish/fallback LLM ---
lp._cache.clear()
lp.deepl_translate = lambda t: None
lp.google_translate = lambda t: ('"Sudah dipikirkan dengan baik"', "mymemory")
segs5 = [{"text_zh": "我想好了"}]
segs5, failed5 = lp.translate_segments(segs5)
assert failed5 == [], failed5
assert segs5[0]["text_id"] == "Sudah dipikirkan dengan baik", segs5
print("TRANSLATE FREE ONLY OK")

# --- frame identik dilewati: sig sama untuk ROI yang sama ---
import numpy as _np2
_a = _np2.zeros((64, 96, 3), dtype=_np2.uint8)
assert lp._frame_sig(_a) == lp._frame_sig(_a.copy())
assert lp._frame_sig(_a) != lp._frame_sig(_a + 1)
print("LOCAL FRAME SIG OK")

# --- metode cepat 2026-11-27: FPS 0.5, Whisper small + beam 1, paralel ---
assert lp.FPS == 0.5, lp.FPS
assert lp.WHISPER_MODEL == "small", lp.WHISPER_MODEL
assert lp.WHISPER_BEAM == 1, lp.WHISPER_BEAM
assert lp._whisper_fingerprint()["model"] == "small"
assert lp._whisper_fingerprint()["beam_size"] == 1
print("LOCAL PERF CONFIG OK")

# --- fusi lokal: timing diperbaiki, whisper-only ditambah, konflik ditandai ---
_ocr = [{"start": 0.0, "end": 2.0, "text_zh": "你好", "bbox": [0.2, 0.66, 0.8, 0.72]}]
_wh = [{"start": 0.2, "end": 1.8, "text": "你好",
        "words": [{"start": 0.2, "end": 1.0, "word": "你"}, {"start": 1.0, "end": 1.8, "word": "好"}]},
       {"start": 3.0, "end": 3.8, "text": "再见", "words": []}]
_fused, _fstats = lp.fuse_segments(_ocr, _wh)
assert _fused[0]["start"] == 0.2 and _fused[0]["end"] == 1.8, _fused
assert _fstats["whisper_only"] == 1 and len(_fused) == 2, (_fstats, _fused)
assert _fused[1]["source"] == "asr", _fused
print("LOCAL FUSE OK")

# --- paralel: OCR + Whisper jalan berbarengan, bukan antre ---
import time as _time
_calls = []
def _fake_ocr(vid, dur):
    _time.sleep(0.4)
    _calls.append("ocr")
    return [{"start": 0.0, "end": 1.0, "text_zh": "你好"}], {"extract": 0.1, "ocr": 0.4}
def _fake_wh(vid, dur):
    _time.sleep(0.4)
    _calls.append("whisper")
    return [], 0.4
lp.extract_segments, lp.whisper_episode = _fake_ocr, _fake_wh
_t0 = _time.time()
_o, _t, _w, _tw = lp.parallel_ocr_whisper("x.mp4", 10.0)
_wall = _time.time() - _t0
assert sorted(_calls) == ["ocr", "whisper"], _calls
assert _wall < 0.7, f"paralel harus < 0.7s, dapat {_wall:.2f}s"
assert _o[0]["text_zh"] == "你好" and _w == [], (_o, _w)
print("LOCAL PARALLEL OK", round(_wall, 2), "s")

# --- OCR API: kode memakai API rapidocr-onnxruntime 1.2.3 (text_detector /
# text_recognizer). Versi 1.4.x menghapus method itu — install tanpa pin
# pernah merusak run lokal 2026-11-27. Tes ini menangkap itu lebih awal.
import importlib.util as _ilu
if _ilu.find_spec("rapidocr_onnxruntime") is not None:
    from rapidocr_onnxruntime import RapidOCR as _ROCR
    _eng = _ROCR()
    for _m in ("text_detector", "text_recognizer", "sorted_boxes", "get_crop_img_list"):
        assert hasattr(_eng, _m), f"RapidOCR tanpa {_m} — cek pin rapidocr-onnxruntime==1.2.3"
    import numpy as _np
    _img = _np.full((120, 400, 3), 255, dtype=_np.uint8)
    _res = lp.ocr_batch(_eng, [(_img, 400, 120)])
    assert isinstance(_res, list) and len(_res) == 1, _res
    print("LOCAL OCR API OK")
else:
    print("LOCAL OCR API SKIP (rapidocr tidak terpasang)")

# --- fingerprint JSON round-trip (bug 2026-11-27): roi tuple vs list.
# fingerprint() lama mengembalikan ROI sebagai tuple; setelah ditulis ke
# JSON lalu dibaca lagi jadi list, perbandingan selalu gagal dan OCR
# selalu diulang walau config tidak berubah.
_fp = lp.fingerprint()
import json as _json2
assert _json2.loads(_json2.dumps(_fp)) == _fp, _fp
assert isinstance(_fp["roi"], list), _fp
print("LOCAL FINGERPRINT ROUNDTRIP OK")

# --- profil per device (2026-11-27): satu kode, setting per device ---
import importlib.util as _ilu2
if _ilu2.find_spec("yaml") is not None:
    _profs = lp.load_profiles()
    assert set(_profs) == {"colab", "kaggle", "pc", "vm", "instabox"}, set(_profs)
    assert "termux" not in _profs, "termux sengaja tidak ada (tidak direkomendasikan)"
    for _name, _p in _profs.items():
        for _k in ("platform", "episodes_dir", "base_out_dir", "fps", "roi",
                   "min_conf", "upscale", "whisper_model", "whisper_beam", "blur_mode",
                   "ocr_engine"):
            assert _k in _p, (_name, _k)
    assert _profs["colab"]["ocr_engine"] == "rapidocr3-gpu"
    assert _profs["kaggle"]["ocr_engine"] == "rapidocr3-gpu"
    assert _profs["pc"]["ocr_engine"] == "rapidocr1-cpu"
    assert _profs["vm"]["ocr_engine"] == "rapidocr1-cpu"
    assert _profs["instabox"]["ocr_engine"] == "rapidocr1-cpu"
    assert _profs["colab"]["mount_drive"] is True
    assert _profs["kaggle"]["mount_drive"] is False
    assert _profs["kaggle"]["episodes_dir"].startswith("/kaggle/input/")
    assert _profs["colab"]["fps"] == 1.0 and _profs["colab"]["whisper_model"] == "large-v3-turbo"
    assert _profs["colab"]["whisper_beam"] == 5
    assert _profs["pc"]["fps"] == 0.5 and _profs["pc"]["whisper_model"] == "small"
    assert _profs["pc"]["whisper_beam"] == 1
    lp.apply_profile("colab")
    assert lp.PROFILE == "colab" and lp.FPS == 1.0
    assert lp.WHISPER_MODEL == "large-v3-turbo" and lp.WHISPER_BEAM == 5
    assert lp.OCR_ENGINE == "rapidocr3-gpu"
    assert lp.fingerprint()["profile"] == "colab"
    assert lp.fingerprint()["ocr"] == "rapidocr3-gpu"
    assert lp._whisper_fingerprint()["profile"] == "colab"
    lp.apply_profile("pc")
    assert lp.PROFILE == "pc" and lp.FPS == 0.5 and lp.WHISPER_MODEL == "small"
    assert lp.OCR_ENGINE == "rapidocr1-cpu"
    assert lp.CRF == 26, lp.CRF
    assert lp.fingerprint()["profile"] == "pc"
    assert lp.fingerprint()["ocr"] == "rapidocr1-cpu"
    try:
        lp.apply_profile("termux")
        raise AssertionError("profil termux harus ditolak")
    except ValueError:
        pass
    print("LOCAL PROFILES OK")
else:
    print("LOCAL PROFILES SKIP (pyyaml tidak terpasang)")
