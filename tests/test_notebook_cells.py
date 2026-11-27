"""Smoke test notebook cells (config -> OCR defs -> translate -> render) di folder temp."""
import json, os, subprocess, sys, tempfile

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

g = {"__name__": "__main__"}
exec(compile(cfg, "config", "exec"), g)

stem = "ç¬¬000001é›†"
vid = os.path.join(eps, stem + ".mp4")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc=size=640x360:rate=24", "-t", "3", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", vid], check=True)

# OCR cell: MAX_EPISODES=0 -> loop kosong, fungsi tetap terdefinisi
g["MAX_EPISODES"] = 0
exec(compile(open(os.path.join(SRC, "nb_new_ocr.py"), encoding="utf-8").read(), "ocr", "exec"), g)
assert callable(g["write_srt"]) and callable(g["probe"]), "fungsi OCR tidak terdefinisi"

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

exec(compile(open(os.path.join(SRC, "nb_new_render.py"), encoding="utf-8").read(), "rd", "exec"), g)
hard = os.path.join(out, "episodes_hardsub_id", stem + "_id_hardsub.mp4")
assert os.path.getsize(hard) > 0, "hardsub tidak dibuat"
print("CELL RENDER OK", os.path.getsize(hard), "bytes")

