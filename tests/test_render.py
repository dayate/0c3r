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
    return ("ID:" + t, "google")

lp.deepl_translate = lambda t: None
lp.google_translate = fake_free
lp.llm_translate = lambda lines: None
segs2 = [{"text_zh": "你好"}, {"text_zh": "再见"}, {"text_zh": "你好"}]
lp.translate_segments(segs2)
assert calls == ["你好", "再见"], calls
assert segs2[0]["text_id"] == "ID:你好" and segs2[2]["text_id"] == "ID:你好"

lp._cache.clear()
lp.google_translate = lambda t: (None, None)
lp.llm_translate = lambda lines: ["LLM:" + x for x in lines]
segs3 = [{"text_zh": "测试"}]
lp.translate_segments(segs3)
assert segs3[0]["text_id"] == "LLM:测试", segs3
print("TRANSLATE OK")
