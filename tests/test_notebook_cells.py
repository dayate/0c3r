"""Smoke test notebook cells (config -> OCR defs -> translate -> render) di folder temp."""
import json, os, subprocess, sys, tempfile
import yaml
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "notebook", "src")
td = tempfile.mkdtemp()
eps = os.path.join(td, "episodes")
out = os.path.join(td, "out")
os.makedirs(eps)

cfg = open(os.path.join(SRC, "nb_new_config.py"), encoding="utf-8").read()
cfg = cfg.replace('EPISODES_DIR = "/content/drive/MyDrive/duanju/episodes"',
                  f'EPISODES_DIR = r"{eps}"')
cfg = cfg.replace('BASE_OUT_DIR = "/content/drive/MyDrive/duanju/suba_hardsub"',
                  f'BASE_OUT_DIR = r"{out}"')
# Profil: jalankan cell config dengan profil pc (nilai yang dipakai tes
# Whisper small / FPS 0.5), dengan dir episode/output diarahkan ke temp.
_raw = yaml.safe_load(open(os.path.join(BASE, "profiles.yaml"), encoding="utf-8"))
_defs = _raw.get("defaults") or {}
_profiles = {}
for _n, _p in (_raw.get("profiles") or {}).items():
    _m = dict(_defs)
    _m.update(_p or {})
    _profiles[_n] = _m
_profiles["pc"]["episodes_dir"] = eps
_profiles["pc"]["base_out_dir"] = out
cfg = cfg.replace('PROFILE = "colab"  # __PROFILE_NAME__', 'PROFILE = "pc"')
cfg = cfg.replace("PROFILES = {}  # __PROFILES_JSON__",
                  "PROFILES = " + repr(_profiles))

g = {"__name__": "__main__"}
exec(compile(cfg, "config", "exec"), g)

# Validator SRT harus tersedia sebelum cell translate / render dijalankan
exec(compile(open(os.path.join(SRC, "nb_new_validate.py"), encoding="utf-8").read(), "validate", "exec"), g)
assert callable(g["validate_segments"]) and callable(g["assert_valid_segments"])

stem = "ç¬¬000001é›†"
vid = os.path.join(eps, stem + ".mp4")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc=size=640x360:rate=24", "-t", "3", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", vid], check=True)

# OCR cell: MAX_EPISODES=0 -> loop kosong, fungsi tetap terdefinisi
g["MAX_EPISODES"] = 0
exec(compile(open(os.path.join(SRC, "nb_new_ocr.py"), encoding="utf-8").read(), "ocr", "exec"), g)
assert callable(g["write_srt"]) and callable(g["probe"]), "fungsi OCR tidak terdefinisi"

# Fixture frame disimpan sebagai base64 (.jpg.b64, teks UTF-8) karena
# snapshot push GitHub hanya menerima file UTF-8 — JPG biner ditolak.
import base64 as _b64
def _fixture_jpg(name):
    _p = os.path.join(BASE, "tests", "fixtures", name + ".jpg.b64")
    _out = os.path.join(td, name + ".jpg")
    with open(_p, encoding="utf-8") as _f:
        _data = _b64.b64decode(_f.read())
    with open(_out, "wb") as _f:
        _f.write(_data)
    return _out

# OCR 3.x di frame asli (fixture frame43 episode 1, detik 43): harus baca 韩沐宸.
# Harness pakai profil pc (ROI 0.05/0.62, MIN_CONF 0.65, UPSCALE 2) -> use_cuda
# False, jadi engine 3.x jalan di CPU (lambat di VM, tapi formatnya sama).
import importlib.util as _ilu3
if _ilu3.find_spec("rapidocr") is not None:
    _fx = _fixture_jpg("frame43")
    _arr, _w, _h, _cw, _ch, _gate = g["load_crop"](_fx)
    assert _gate, "frame 43 harus lolos text gate"
    _eng3 = g["get_engine"]()
    _outs = g["ocr_batch"](_eng3, [(_arr, _cw, _ch)])
    assert len(_outs) == 1, _outs
    _txt3, _box3 = _outs[0]
    assert "韩沐宸" in _txt3, _txt3
    assert _box3 and all(0.0 <= v <= 1.0 for v in _box3), _box3
    # Kartu nama (frame 46, detik 46): engine mentah mendeteksi nama +
    # jabatan, tapi ocr_batch harus membuang keduanya (filter per deteksi).
    # Pakai setting colab (ROI 0.55) seperti probe aslinya.
    _old = (g["ROI"], g["MIN_CONF"], g["UPSCALE"])
    g["ROI"], g["MIN_CONF"], g["UPSCALE"] = (0.05, 0.55, 0.95, 0.93), 0.55, 3
    _fx46 = _fixture_jpg("frame46_namecard")
    _arr46, _w46, _h46, _cw46, _ch46, _gate46 = g["load_crop"](_fx46)
    _raw46 = _eng3(_arr46)
    assert any("温薏" in str(t) for t in (_raw46.txts or ())), _raw46.txts
    _outs46 = g["ocr_batch"](_eng3, [(_arr46, _cw46, _ch46)])
    g["ROI"], g["MIN_CONF"], g["UPSCALE"] = _old
    assert _outs46 == [("", None)], _outs46
    print("CELL OCR V3 NAME CARD OK")
    # Frame kosong -> ("", None), bukan error (txts/scores None di 3.x).
    _np = g["np"]
    _blank = g["ocr_batch"](_eng3, [(_np.zeros((200, 300, 3), dtype=_np.uint8), 300, 200)])
    assert _blank == [("", None)], _blank
    print("CELL OCR V3 OK", _txt3, _box3)
else:
    print("CELL OCR V3 SKIP (rapidocr 3.x tidak terpasang)")

# Whisper cell: butuh fungsi util dari cell OCR (natural_key, write_srt, probe),
# jadi dieksekusi setelah OCR — sama seperti urutan di notebook.
g["MAX_EPISODES"] = 0
exec(compile(open(os.path.join(SRC, "nb_new_whisper.py"), encoding="utf-8").read(), "whisper", "exec"), g)
assert callable(g["fuse_segments"]), "fungsi fusi Whisper tidak terdefinisi"
_ocr = [{"start": 0.0, "end": 2.0, "text_zh": "你好", "bbox": [0.2, 0.66, 0.8, 0.72]}]
_wh = [{"start": 0.2, "end": 1.8, "text": "你好",
        "words": [{"start": 0.2, "end": 1.0, "word": "你"}, {"start": 1.0, "end": 1.8, "word": "好"}]},
       {"start": 3.0, "end": 3.8, "text": "再见", "words": []}]
_fused, _stats = g["fuse_segments"](_ocr, _wh)
assert _fused[0]["start"] == 0.2 and _fused[0]["end"] == 1.8, _fused
assert _stats["whisper_only"] == 1 and len(_fused) == 2, (_stats, _fused)
print("CELL WHISPER FUSE OK")

# _load_wav_array: WAV 16k mono -> float32, tanpa lewat PyAV decode_audio
# (faster-whisper 1.2.1 + PyAV 19 crash di av.open metadata_errors)
import wave as _wave, struct as _struct
_wav = os.path.join(td, "t.wav")
with _wave.open(_wav, "wb") as _wf:
    _wf.setnchannels(1); _wf.setsampwidth(2); _wf.setframerate(16000)
    _wf.writeframes(_struct.pack("<16000h", *([1000] * 16000)))
_arr = g["_load_wav_array"](_wav)
assert _arr.dtype.name == "float32" and _arr.shape == (16000,), _arr.shape
assert abs(float(_arr[0]) - 1000 / 32768.0) < 1e-6
print("CELL WHISPER WAV OK")

# Tuning cell: tanpa ipywidgets di VM, UI dilewati tapi fungsi tetap terdefinisi
_exec_ep = g["EPISODES_DIR"]
exec(compile(open(os.path.join(SRC, "nb_new_tune.py"), encoding="utf-8").read(), "tune", "exec"), g)
g["EPISODES_DIR"] = _exec_ep
assert callable(g["_prepare_crop"]) and callable(g["_ocr_frame"]) and callable(g["_draw_result"])
_timg = Image.new("RGB", (540, 960), (20, 20, 20))
_tarr, _w, _h, _cw, _ch = g["_prepare_crop"](_timg, (0.05, 0.62, 0.95, 0.93), 2, 1080)
assert _tarr.shape == (594, 972, 3), _tarr.shape
class _FakeOut:
    # Format RapidOCR 3.x: RapidOCROutput (.txts/.scores/.boxes), bukan tuple.
    txts = ("你好世界", "再见")
    scores = (0.92, 0.40)
    boxes = [[[0, 0], [100, 0], [100, 20], [0, 20]],
             [[0, 30], [80, 30], [80, 50], [0, 50]]]
class _FakeEngine:
    def __call__(self, a):
        return _FakeOut()
_det = g["_ocr_frame"](_FakeEngine(), _tarr, 0.65)
assert len(_det) == 1 and _det[0][0] == "你好世界", _det
_drawn = g["_draw_result"](_timg, (0.05, 0.62, 0.95, 0.93), _det, 2, _cw, _ch,
                           os.path.join(td, "tune_res.png"))
assert _drawn and os.path.getsize(_drawn) > 1000
print("CELL TUNE OK")

# Whisper fallback: model GPU gagal libcublas -> ganti CPU, chunk tetap jadi
import wave as _wave2, struct as _struct2
_fwav = os.path.join(td, "fallback.wav")
with _wave2.open(_fwav, "wb") as _wf:
    _wf.setnchannels(1); _wf.setsampwidth(2); _wf.setframerate(16000)
    _wf.writeframes(_struct2.pack("<16000h", *([1000] * 16000)))
class _GpuModel:
    def transcribe(self, audio, **kw):
        raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
class _CpuModel:
    def transcribe(self, audio, **kw):
        class _W:
            def __init__(self): self.start, self.end, self.word = 0.0, 1.0, "你"
        class _S:
            def __init__(self):
                self.start, self.end, self.text = 0.0, 1.0, "你好"
                self.words = [_W()]
                self.avg_logprob = -0.1
        return [_S()], {}
g["_get_model"] = lambda force_cpu=False: _CpuModel()
_got = g["_transcribe_chunk"](_GpuModel(), _fwav, 0.0, 1.0)
assert len(_got) == 1 and _got[0]["text"] == "你好", _got
assert g["_cpu_model"] is not None
print("CELL WHISPER CUBLAS FALLBACK OK")

# Validator cadangan: cell Translate jalan tanpa cell 3b tetap punya validator
g2 = dict(g)
g2.pop("validate_segments", None)
g2.pop("assert_valid_segments", None)
exec(compile(open(os.path.join(SRC, "nb_new_translate.py"), encoding="utf-8").read(), "translate2", "exec"), g2)
assert callable(g2["assert_valid_segments"])
assert g2["validate_segments"]([{"start": 0.5, "end": 1.5, "text_zh": "你好", "text_id": "你好"}]), \
    "validator cadangan harus menolak Mandarin di SRT ID"
_bad = [
    {"start": 2.0, "end": 4.42, "text_zh": "你好吗", "text_id": "Apa kabar kamu hari ini"},
    {"start": 3.64, "end": 5.1, "text_zh": "很好", "text_id": "Aku baik-baik saja, terima kasih"},
    {"start": 10.0, "end": 12.0, "text_zh": "我想去看看那个地方", "text_id": "Aku ingin pergi melihat tempat itu besok pagi"},
]
assert g2["validate_segments"](_bad), "kasus nyata harus ditolak sebelum normalisasi"
_fixed, _ns = g2["normalize_segments"](_bad)
assert g2["validate_segments"](_fixed) == [], g2["validate_segments"](_fixed)
assert all(len(l) <= 42 for s in _fixed for l in (s["text_id"] or "").split("\n"))
print("CELL TRANSLATE NORMALIZE OK", _ns)

g["MAX_EPISODES"] = 200
ep_json = os.path.join(out, "per_episode", stem + "_ocr.json")
segs = [
    {"start": 0.5, "end": 1.5, "text_zh": "ä½ å¥½", "bbox": [0.2, 0.66, 0.8, 0.72]},
    {"start": 2.0, "end": 2.8, "text_zh": "å†è§", "bbox": [0.25, 0.67, 0.75, 0.73]},
]
with open(ep_json, "w", encoding="utf-8") as f:
    json.dump({"episode": stem, "video_file": os.path.basename(vid), "duration": 3.0,
               "width": 640, "height": 360, "segments": segs}, f, ensure_ascii=False)

g["_cache"] = {"ä½ å¥½": "Halo", "å†è§": "Sampai jumpa"}
exec(compile(open(os.path.join(SRC, "nb_new_translate.py"), encoding="utf-8").read(), "tr", "exec"), g)

data = json.load(open(ep_json, encoding="utf-8"))
assert [s.get("text_id") for s in data["segments"]] == ["Halo", "Sampai jumpa"], data["segments"]
assert os.path.exists(os.path.join(out, "per_episode", stem + "_id.srt"))
print("CELL TRANSLATE OK")

# Baris non-Mandarin (sampah OCR latin) harus diteruskan apa adanya,
# bukan memblokir seluruh episode — kasus nyata "ALSURR 120." ep 2.
stem2 = "第000002集"
vid2 = os.path.join(eps, stem2 + ".mp4")
open(vid2, "wb").write(open(vid, "rb").read())
ep_json2 = os.path.join(out, "per_episode", stem2 + "_ocr.json")
segs2 = [
    {"start": 61.92, "end": 62.44, "text_zh": "ALSURR 120.", "bbox": [0.2, 0.66, 0.8, 0.72]},
    {"start": 2.0, "end": 2.8, "text_zh": "你好", "bbox": [0.25, 0.67, 0.75, 0.73]},
]
with open(ep_json2, "w", encoding="utf-8") as f:
    json.dump({"episode": stem2, "video_file": os.path.basename(vid2), "duration": 3.0,
               "width": 640, "height": 360, "segments": segs2}, f, ensure_ascii=False)
g5 = dict(g)
g5["_cache"] = {"你好": "Halo"}
g5["_cache_prov"] = {}
exec(compile(open(os.path.join(SRC, "nb_new_translate.py"), encoding="utf-8").read(), "translate5", "exec"), g5)
data2 = json.load(open(ep_json2, encoding="utf-8"))
# Segmen ditulis terurut waktu: 你好 (2.0s) dulu, baru "ALSURR 120." (61.92s).
assert [s.get("text_id") for s in data2["segments"]] == ["Halo", "ALSURR 120."], data2["segments"]
assert g5["_cache_prov"].get("ALSURR 120.") == "passthrough"
assert os.path.exists(os.path.join(out, "per_episode", stem2 + "_id.srt"))
print("CELL TRANSLATE PASSTHROUGH OK")
# Tes berikutnya (guard, renormalize) mengeksekusi cell Translate lagi di
# namespace g — daftarkan hasil episode 2 di cache g supaya tidak kena
# provider asli (yang di VM kena 429) saat pengujian ulang.
g["_cache"].update({"你好": "Halo", "ALSURR 120.": "ALSURR 120."})
g["_cache_prov"].update({"ALSURR 120.": "passthrough"})

# Guard tidak boleh bolong: kalau cell 3b LAMA yang jalan (validator ada
# tapi normalize belum ada), cell Translate tetap harus mendefinisikan
# normalize_segments, bukan NameError / diam-diam skip.
g3 = dict(g)
g3.pop("normalize_segments", None)
g3["assert_valid_segments"] = lambda segs, where="": True  # validator lama
exec(compile(open(os.path.join(SRC, "nb_new_translate.py"), encoding="utf-8").read(), "translate3", "exec"), g3)
assert callable(g3["normalize_segments"]), "guard harus mendefinisikan normalize walau validator lama ada"
print("CELL TRANSLATE GUARD OK")

# Jalankan lagi cell Translate di g yang sama: episode sudah diterjemah
# dan SRT ID sudah ada — harus dinormalisasi ulang, bukan skip buta.
exec(compile(open(os.path.join(SRC, "nb_new_translate.py"), encoding="utf-8").read(), "translate4", "exec"), g)
assert g["validate_segments"](json.load(open(ep_json, encoding="utf-8"))["segments"]) == []
print("CELL TRANSLATE RENORMALIZE OK")

exec(compile(open(os.path.join(SRC, "nb_new_render.py"), encoding="utf-8").read(), "rd", "exec"), g)
hard = os.path.join(out, "episodes_hardsub_id", stem + "_id_hardsub.mp4")
assert os.path.getsize(hard) > 0, "hardsub tidak dibuat"
print("CELL RENDER OK", os.path.getsize(hard), "bytes")

# Kartu nama/peran dibuang di cell Translate (definisi unconditional)
_card = {"start": 119.0, "end": 121.0, "text_zh": "丰宸集团总裁", "bbox": [0.05, 0.50, 0.12, 0.65]}
assert g["is_name_card"](_card["text_zh"], _card["bbox"])
_kept, _n = g["drop_name_cards"]([_card, {"start": 0.5, "end": 1.5, "text_zh": "你好", "bbox": [0.2, 0.66, 0.8, 0.72]}])
assert _n == 1 and len(_kept) == 1
print("CELL NAME CARD OK")

# Blur dynamic: radius/power baru + jendela ber-padding
# (radius 20 di-config, tapi dibatasi setengah tinggi crop: 30px -> 14)
_bsegs = [{"start": 0.5, "end": 1.5, "text_zh": "你好", "bbox": [0.2, 0.66, 0.8, 0.72]}]
_band = g["compute_band"](_bsegs, 360)
_fc, _ = g["build_blur"](_bsegs, _band, 640, 360, "dynamic")
assert "luma_radius=14" in _fc and "luma_power=3" in _fc, _fc
assert "between(t,0.100,1.900)" in _fc, _fc
print("CELL BLUR DYNAMIC OK")


# Metode cepat 2026-11-27: Whisper "small" + beam 1 (dari cell config),
# bukan large-v3-turbo beam 5. Cell tetap bisa jalan sendiri (default small).
assert g["WHISPER_MODEL"] == "small", g["WHISPER_MODEL"]
assert g["WHISPER_BEAM"] == 1, g["WHISPER_BEAM"]
assert g["_whisper_fingerprint"]()["model"] == "small"
assert g["_whisper_fingerprint"]()["beam_size"] == 1
assert g["FPS"] == 0.5, g["FPS"]
print("CELL WHISPER SMALL OK")

# Fingerprint JSON round-trip (bug 2026-11-27, sama seperti lokal):
# roi tuple bikin resume chunk/episode di cell OCR tidak pernah cocok.
import json as _json
_fp = g["fingerprint"]()
assert _json.loads(_json.dumps(_fp)) == _fp, _fp
assert isinstance(_fp["roi"], list), _fp
# Harness pakai profil pc -> mesin OCR 1.2.3 CPU.
assert _fp["ocr"] == "rapidocr1-cpu", _fp
print("CELL FINGERPRINT ROUNDTRIP OK")

# Profil di notebook (2026-11-27): generator menyuntik PROFILES ke cell profil
# tersendiri (pretty-print) + PROFILE ke cell config; judul section jadi
# markdown cell; varian kaggle tanpa mount Drive.
import subprocess as _sp
for _prof, _out in (("colab", "colab-suba-hardsub-v2.ipynb"),
                    ("kaggle", "kaggle-suba-hardsub-v2.ipynb")):
    _r = _sp.run([sys.executable, "notebook/build_colab_nb.py", "--profile", _prof],
                 capture_output=True, text=True, cwd=BASE)
    assert _r.returncode == 0, _r.stderr
    _nb = json.load(open(os.path.join(BASE, "notebook", _out), encoding="utf-8"))
    # colab 25 cell; kaggle 24 (langkah mount Drive jadi 1 cell markdown).
    assert len(_nb["cells"]) == (25 if _prof == "colab" else 24), len(_nb["cells"])
    # Judul section harus markdown cell, bukan code cell berisi komentar.
    _headers = [c for c in _nb["cells"]
                if "".join(c.get("source", [])).startswith("## ")]
    assert _headers, "tidak ada cell judul"
    assert all(c["cell_type"] == "markdown" for c in _headers), [
        "".join(c.get("source", [])).split("\n")[0] for c in _headers
        if c["cell_type"] != "markdown"]
    _srcs = ["".join(c.get("source", [])) for c in _nb["cells"]]
    # Cell profil tersendiri (dict lengkap), cell config tinggal memakai PROFILES.
    _prof_src = next(s for s in _srcs if "PROFILES = {" in s)
    _cfg_src = next(s for s in _srcs if "PROFILES" in s and "EPISODES_DIR" in s)
    assert "PROFILES = {" not in _cfg_src, "config cell masih membawa dict PROFILES"
    assert "globals().get(\"PROFILES\", {})" in _cfg_src, "guard PROFILES hilang"
    _g2 = {"__name__": "__main__"}
    exec(compile(_prof_src, "profiles-" + _prof, "exec"), _g2)
    exec(compile(_cfg_src, "config-" + _prof, "exec"), _g2)
    assert set(_g2["PROFILES"]) == {"colab", "kaggle", "pc", "vm", "instabox"}
    assert "termux" not in _g2["PROFILES"]
    assert _g2["PROFILE"] == _prof
    assert any("drive.mount" in s for s in _srcs) == (_prof == "colab"), _prof
    if _prof == "kaggle":
        assert _g2["EPISODES_DIR"].startswith("/kaggle/input/"), _g2["EPISODES_DIR"]
        assert _g2["BASE_OUT_DIR"].startswith("/kaggle/working/"), _g2["BASE_OUT_DIR"]
        assert _g2["FPS"] == 1.0 and _g2["WHISPER_MODEL"] == "large-v3-turbo"
    else:
        assert _g2["EPISODES_DIR"].startswith("/content/drive/"), _g2["EPISODES_DIR"]
    # OCR GPU (2026-11-27): profil notebook pakai RapidOCR 3.x.
    assert _g2["OCR_ENGINE"] == "rapidocr3-gpu", _g2["OCR_ENGINE"]
    assert _g2["PROFILES"][_prof]["ocr_engine"] == "rapidocr3-gpu"
    # Cell install: rapidocr 3.x + onnxruntime-gpu, bukan 1.2.3.
    _install_src = next(s for s in _srcs if "pip install" in s)
    assert "rapidocr" in _install_src and "rapidocr-onnxruntime" not in _install_src, _install_src
    assert "onnxruntime-gpu" in _install_src, _install_src
    if _prof == "colab":
        assert "nvidia-cudnn-cu13" in _install_src and "nvidia-cublas-cu12" in _install_src
        # cudnn-cu12 tidak boleh ada di BARIS pip (komentar boleh menyebutnya
        # sebagai paket yang diganti) — cek barisnya, bukan seluruh cell.
        _pip = [l for l in _install_src.split("\n") if l.startswith("!pip install")]
        assert _pip and "nvidia-cudnn-cu12" not in _pip[0], _pip
print("CELL PROFILE OK")
