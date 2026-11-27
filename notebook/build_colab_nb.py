import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "colab-suba-hardsub-v2.ipynb")
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

cells = [
    c(code("nb_new_md0.md"), "md"),
    c("## 1 — Mount Google Drive"),
    c("from google.colab import drive\ndrive.mount('/content/drive')\nprint('Google Drive berhasil di-mount!')"),
    c("## 2 — Install Dependensi & Font Pendukung"),
    c(code("nb_new_install.py")),
    c("## 3 — Konfigurasi Utama"),
    c(code("nb_new_config.py")),
    c(code("nb_new_md7.md"), "md"),
    c("## 4 — OCR (Mandarin)"),
    c(code("nb_new_ocr.py")),
    c("## 5 — Translate (Gratis dulu, LLM fallback)"),
    c(code("nb_new_translate.py")),
    c("## 6 — Blur Hardsub + Burn Subtitle Indonesia"),
    c(code("nb_new_render.py")),
    c("## 7 — Merge Seluruh Subtitle (.SRT) Lengkap"),
    c(code("nb_new_merge_srt.py")),
    c("## 8 — Merge Seluruh Episode Video (Sudah Hardsub ID) Jadi 1 File Utuh (Opsional)"),
    c(code("nb_new_merge_vid.py")),
]

nb = {
    "cells": cells,
    "metadata": {
        "colab": {"name": "colab-suba-hardsub-v2.ipynb", "provenance": []},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 0,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print("tulis", OUT, len(cells), "cells")
