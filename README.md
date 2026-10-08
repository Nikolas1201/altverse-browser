# AltVerse Browser

A local, offline AI "alternate universe browser". Type any URL + year and a
local LLM hallucinates the entire webpage — then browse it: clickable links,
working search, back/forward history, per-timeline memory.

![Requires Windows + NVIDIA GPU](https://img.shields.io/badge/Windows-NVIDIA-green)

## Install (cousin-proof)

1. Download **AltVerseSetup.exe** from [Releases](../../releases).
2. Run it, pick a model (downloaded ones are listed, best pick tagged
   **(recommended)**), keep **Download the AI model now** checked.
3. It installs Python + Lemonade Server itself if missing, downloads the
   model, and launches. Close the browser window and the server quits too.

Needs: Windows 11 recommended, NVIDIA GPU, internet (first launch downloads
the model: 2.4 GB for the 4B, ~17 GB for the 30B).

## How it works

- [Lemonade Server](https://lemonade-server.ai) runs the local model
  (CUDA llama.cpp backend).
- `altverse/app.py` (Flask) prompts it for raw era-authentic HTML and renders
  it in a sandboxed iframe, with a hook that makes in-page search and links
  browse deeper into the timeline.
- Session memory: each generation sees excerpts of your last 2 pages, so
  lore, companies, and characters persist.
- The installer (`altverse-installer/`, Inno Setup 6) scans your GPU and your
  downloaded models to recommend the right brain.

## Project layout

- `altverse/app.py` — the browser server (needs `pip install flask requests`)
- `altverse/AltVerse.bat` — personal launcher (model baked in)
- `altverse-installer/installer.iss` — Inno Setup script
- `altverse-installer/Launcher.bat` — generic launcher (reads `model.txt`)
- `altverse-installer/DownloadModel.bat` — install-time model download
- `altverse-installer/README.txt` — end-user instructions
