import glob, json, os, re


def natural_key(path):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def fmt_srt_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def fmt_hms(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


json_files = sorted(glob.glob(os.path.join(PER_EP_DIR, "*_ocr.json")), key=natural_key)[:MAX_EPISODES]
merged_segs, chapters, offset = [], [], 0.0

for jf in json_files:
    with open(jf, encoding="utf-8") as f:
        data = json.load(f)
    ep_name = data.get("episode", os.path.basename(jf))
    dur = float(data.get("duration", 0.0))
    chapters.append(f"{fmt_hms(offset)} - {ep_name}")
    for seg in data.get("segments", []):
        merged_segs.append({
            "start": round(offset + float(seg["start"]), 3),
            "end": round(offset + float(seg["end"]), 3),
            "text_zh": seg.get("text_zh", ""),
            "text_id": seg.get("text_id", ""),
        })
    offset += dur

merged_id_srt = os.path.join(MERGED_DIR, "merged_all_id.srt")
merged_zh_srt = os.path.join(MERGED_DIR, "merged_all_zh.srt")
chapter_txt = os.path.join(MERGED_DIR, "merged_chapter_timestamps.txt")

with open(merged_id_srt, "w", encoding="utf-8") as f_id, open(merged_zh_srt, "w", encoding="utf-8") as f_zh:
    idx_id = idx_zh = 1
    for seg in merged_segs:
        ts = f"{fmt_srt_time(seg['start'])} --> {fmt_srt_time(seg['end'])}"
        if seg["text_id"].strip():
            f_id.write(f"{idx_id}\n{ts}\n{seg['text_id'].strip()}\n\n")
            idx_id += 1
        if seg["text_zh"].strip():
            f_zh.write(f"{idx_zh}\n{ts}\n{seg['text_zh'].strip()}\n\n")
            idx_zh += 1

with open(chapter_txt, "w", encoding="utf-8") as fc:
    fc.write("\n".join(chapters))

print(f"Total durasi: {fmt_hms(offset)} | Total baris: {len(merged_segs)}")
print("SRT ID gabungan:", merged_id_srt)
print("SRT ZH gabungan:", merged_zh_srt)
