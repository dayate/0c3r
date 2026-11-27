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

# filter statis harus tanpa enable= saat ALWAYS_BLUR
band = lp.compute_band(segs, 360)
fc, _ = lp.build_blur(segs, band, 640, 360, "static")
assert "enable=" not in fc, fc
lp.ALWAYS_BLUR = False
fc2, _ = lp.build_blur(segs, band, 640, 360, "static")
assert "enable=" in fc2
print("FILTER OK")

# --- translate: gratis dulu, LLM fallback ---
lp.TR_CACHE_PATH = os.path.join(td, "cache.json")
lp._cache.clear()
calls = []

def fake_free(t):
    calls.append(t)
    return ({"你好": "Halo", "再见": "Sampai jumpa"}.get(t, "Terjemahan"), "google")

lp.deepl_translate = lambda t: None
lp.google_translate = fake_free
lp.llm_translate = lambda lines: None
segs2 = [{"text_zh": "你好"}, {"text_zh": "再见"}, {"text_zh": "你好"}]
segs2, failed2 = lp.translate_segments(segs2)
assert failed2 == [], failed2
assert calls == ["你好", "再见"], calls
assert segs2[0]["text_id"] == "Halo" and segs2[2]["text_id"] == "Halo"

lp._cache.clear()
lp.google_translate = lambda t: (None, None)
lp.llm_translate = lambda lines: ["Tes" for _ in lines]
segs3 = [{"text_zh": "测试"}]
segs3, failed3 = lp.translate_segments(segs3)
assert failed3 == [], failed3
assert segs3[0]["text_id"] == "Tes", segs3
print("TRANSLATE OK")

# --- translate: gagal di semua jalur -> masuk daftar gagal, text_id kosong ---
lp._cache.clear()
lp.google_translate = lambda t: (None, None)
lp.llm_translate = lambda lines: None
segs4 = [{"text_zh": "你好"}]
segs4, failed4 = lp.translate_segments(segs4)
assert len(failed4) == 1 and failed4[0]["text_zh"] == "你好", failed4
assert segs4[0]["text_id"] == "", segs4
assert lp.validate_segments(segs4), "validator harus menolak baris belum diterjemah"
print("TRANSLATE FAIL OK")

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
assert "luma_radius=15" in fc_dyn and "luma_power=3" in fc_dyn, fc_dyn
assert "between(t,0.100,1.900)" in fc_dyn, fc_dyn  # 0.5-0.4 s/d 1.5+0.4 s
no_bbox = [{"start": 0.5, "end": 1.5, "text_zh": "你好", "text_id": "Halo"}]
fc_nb, _ = lp.build_blur(no_bbox, band, 640, 360, "dynamic")
assert fc_nb is not None and "between(t,0.100,1.900)" in fc_nb, fc_nb
print("BLUR DYNAMIC OK")

# --- translate: kutip dibersihkan + polish LLM untuk baris MyMemory ---
os.environ["TIPROUTER_API_KEY"] = "test-key"
lp.POLISH_WITH_LLM = True
lp._cache.clear()
lp.deepl_translate = lambda t: None
lp.google_translate = lambda t: ('"Sudah dipikirkan dengan baik"', "mymemory")
lp.llm_translate = lambda lines, system=None: ["Aku sudah memutuskannya" for _ in lines]
segs5 = [{"text_zh": "我想好了"}]
segs5, failed5 = lp.translate_segments(segs5)
assert failed5 == [], failed5
assert segs5[0]["text_id"] == "Aku sudah memutuskannya", segs5
# Tanpa key LLM, polish dilewati dan kutip tetap dibersihkan
del os.environ["TIPROUTER_API_KEY"]
lp._cache.clear()
segs6 = [{"text_zh": "我想好了"}]
segs6, failed6 = lp.translate_segments(segs6)
assert segs6[0]["text_id"] == "Sudah dipikirkan dengan baik", segs6
print("TRANSLATE POLISH OK")

# Polish jalan untuk baris cache lama (provider tidak tercatat), sekali saja
os.environ["TIPROUTER_API_KEY"] = "test-key"
lp._cache.clear()
lp._cache_prov.clear()
lp._cache["我想好了"] = "Sudah dipikirkan dengan baik"
lp.llm_translate = lambda lines, system=None: ["Aku sudah memutuskannya" for _ in lines]
segs7 = [{"text_zh": "我想好了"}]
segs7, _ = lp.translate_segments(segs7)
assert segs7[0]["text_id"] == "Aku sudah memutuskannya", segs7
assert lp._cache_prov.get("我想好了") == "polished", lp._cache_prov
calls7 = []
lp.llm_translate = lambda lines, system=None: calls7.append(lines) or ["X"]
segs7b, _ = lp.translate_segments(segs7)
assert calls7 == [], "baris yang sudah di-polish jangan di-polish lagi"
assert segs7b[0]["text_id"] == "Aku sudah memutuskannya", segs7b
del os.environ["TIPROUTER_API_KEY"]
print("TRANSLATE POLISH CACHE OK")

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
