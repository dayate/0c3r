"""Build notebook Suba dari notebook/src/*.py.

Profil per device (profiles.yaml): --profile colab (default) atau kaggle.
- colab : mount Google Drive, install nvidia-cublas/cudnn, path Drive.
- kaggle: tanpa mount Drive (input dari dataset), tanpa install cublas
  (sudah ada di image Kaggle), path /kaggle/input + /kaggle/working.
Profil lain (pc/vm/instabox) hanya untuk local_pipeline.py, bukan notebook.

Isi profiles.yaml disuntik ke cell profil tersendiri (PROFILES, pretty-print)
dan nama profil terpilih ke cell konfigurasi (PROFILE), jadi notebook hasil
build tetap 1 file yang bisa di-upload langsung. Cell konfigurasi tidak lagi
membawa dict PROFILES yang panjang; kalau cell profil dilewati saat run,
config jatuh ke default colab (sama seperti menjalankan src mentah).
Judul section dibuat sebagai markdown cell, bukan code cell berisi komentar.
"""
import argparse, json, os, pprint

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML tidak ada: pip install pyyaml")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(HERE, "src")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().rstrip("\n")


def code(name):
    return read(os.path.join(SRC, name))


def c(src, kind="code"):
    lines = src.split("\n")
    if kind == "code":
        return {"cell_type": "code", "execution_count": None, "metadata": {},
                "outputs": [], "source": [l + "\n" for l in lines[:-1]] + [lines[-1]]}
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines[:-1]] + [lines[-1]]}


def load_profiles():
    with open(os.path.join(REPO, "profiles.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    defaults = data.get("defaults") or {}
    out = {}
    for name, prof in (data.get("profiles") or {}).items():
        merged = dict(defaults)
        merged.update(prof or {})
        out[name] = merged
    return out


def main():
    ap = argparse.ArgumentParser(description="Build notebook Suba")
    ap.add_argument("--profile", choices=("colab", "kaggle"), default="colab",
                    help="profil notebook (colab/kaggle)")
    ap.add_argument("--out", default=None,
                    help="file .ipynb hasil (default per profil)")
    args = ap.parse_args()

    profiles = load_profiles()
    prof = profiles[args.profile]
    out_name = ("colab-suba-hardsub-v2.ipynb" if args.profile == "colab"
                else "kaggle-suba-hardsub-v2.ipynb")
    out = args.out or os.path.join(HERE, out_name)

    # Cell profil tersendiri: dict lengkap (defaults sudah digabung), ditulis
    # multi-baris supaya enak dibaca; cell config tinggal memakai PROFILES.
    # pprint (bukan json.dumps): dict Python butuh True/False, JSON pakai true/false.
    profiles_src = (
        "# Profil per device — dibuat otomatis dari profiles.yaml, jangan edit manual.\n"
        "# Ganti profil lewat PROFILE di cell konfigurasi berikut.\n"
        "PROFILES = " + pprint.pformat(profiles, indent=1, width=100, sort_dicts=False)
    )

    # Cell konfigurasi: PROFILE disuntik; PROFILES diambil dari cell profil
    # kalau sudah di-run, kalau belum jatuh ke {} (= default colab di bawah).
    config = code("nb_new_config.py")
    config = config.replace('PROFILE = "colab"  # __PROFILE_NAME__',
                            f'PROFILE = "{args.profile}"')
    config = config.replace("PROFILES = {}  # __PROFILES_JSON__",
                            "PROFILES = globals().get(\"PROFILES\", {})  # dari cell profil di atas")

    if prof.get("mount_drive"):
        first_cells = [
            c("## 1 — Mount Google Drive", "md"),
            c("from google.colab import drive\ndrive.mount('/content/drive')\nprint('Google Drive berhasil di-mount!')"),
        ]
        install = code("nb_new_install.py")
    else:
        first_cells = [
            c("## 1 — Input Kaggle (dataset, bukan Drive)\n"
              "- Upload episode sebagai **dataset privat** di Kaggle (Add Data → Upload).\n"
              "- Sesuaikan `EPISODES_DIR` di cell konfigurasi dengan slug dataset-mu,\n"
              "  contoh: `/kaggle/input/duanju-episodes`.\n"
              "- Output + checkpoint ada di `/kaggle/working/suba_hardsub` (maks ~20 GB,\n"
              "  unduh sebelum session berakhir — mesin Kaggle itu ephemeral).\n"
              "- Nyalakan **Internet On** (Settings) supaya model Whisper bisa di-download\n"
              "  dari HuggingFace dan API translate/LLM bisa dijangkau.", "md"),
        ]
        install = code("nb_new_install_kaggle.py")

    cells = [
        c(code("nb_new_md0.md").replace("(Colab GPU)", "(Kaggle GPU)")
          if args.profile == "kaggle" else code("nb_new_md0.md"), "md"),
        *first_cells,
        c("## 2 — Install Dependensi & Font Pendukung", "md"),
        c(install),
        c("## 3 — Konfigurasi Utama", "md"),
        c(profiles_src),
        c(config),
        c("## 3b — Validator SRT", "md"),
        c(code("nb_new_validate.py")),
        c("## 3c — Tuning OCR (GUI, jalankan sebelum OCR)", "md"),
        c(code("nb_new_tune.py")),
        c(code("nb_new_md7.md"), "md"),
        c("## 4 — OCR (Mandarin)", "md"),
        c(code("nb_new_ocr.py")),
        c("## 4b — Whisper Timing + Fusi (cell terpisah, boleh dilewati)", "md"),
        c(code("nb_new_whisper.py")),
        c("## 5 — Translate (Gratis dulu, LLM fallback)", "md"),
        c(code("nb_new_translate.py")),
        c("## 6 — Blur Hardsub + Burn Subtitle Indonesia", "md"),
        c(code("nb_new_render.py")),
        c("## 7 — Merge Seluruh Subtitle (.SRT) Lengkap", "md"),
        c(code("nb_new_merge_srt.py")),
        c("## 8 — Merge Seluruh Episode Video (Sudah Hardsub ID) Jadi 1 File Utuh (Opsional)", "md"),
        c(code("nb_new_merge_vid.py")),
    ]

    nb = {
        "cells": cells,
        "metadata": {
            "colab": {"name": os.path.basename(out), "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
    print("tulis", out, len(cells), "cells", "| profil:", args.profile)


if __name__ == "__main__":
    main()
