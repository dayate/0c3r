import glob, os, subprocess

MERGE_ALL_VIDEOS = True


def natural_key(path):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in __import__("re").split(r"(\d+)", name)]


if MERGE_ALL_VIDEOS:
    hard_vids = sorted(glob.glob(os.path.join(HARDSUB_EP_DIR, "*_id_hardsub.mp4")), key=natural_key)[:MAX_EPISODES]
    if hard_vids:
        list_path = os.path.join(WORK_DIR, "hardsub_concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in hard_vids:
                f.write("file '" + p.replace("'", "'\\''") + "'\n")
        out_merged_mp4 = os.path.join(MERGED_DIR, "merged_all_episodes_id_hardsub.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", list_path, "-c", "copy", out_merged_mp4], check=True)
        print("Video maraton hardsub selesai:", out_merged_mp4)
