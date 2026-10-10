AltVerse Browser - local AI alternate-universe browser
====================================================

INSTALL: run AltVerseSetup.exe, pick a model on the AI Model page,
keep "Download the AI model now" checked, and it launches by itself.
A couple of clicks, then everything works. Updates are detected
automatically (back to v1.0.0) and keep your model choice.

WHAT IT INSTALLS FOR YOU:
- Python (if missing), via winget
- Lemonade Server (the local AI backend), via winget
- WebView2 runtime (powers the app window), via winget
- the Python packages (flask, requests, pywebview, waitress)
- the AI model you picked

HOW IT RUNS:
AltVerse opens as its own desktop window - no Chrome, Edge or Firefox is
launched, and there is no black console window. Closing the window quits
everything. First launch may take longer while the model loads.

CHANGE YOUR MIND ABOUT THE MODEL LATER:
Open model.txt in the install folder. Line 1 = model id, line 2 = ctx size.
  Poor mans AI:  Qwen3-4B-Instruct-2507-GGUF  +  4096
  Nice 30B:      Qwen3-Coder-30B-A3B-Instruct-Q4_K_M  +  8192
Save and launch again, or just pick a different one in the app's model menu.

ADDING MORE MODELS:
In the app, the "+" next to the model menu searches HuggingFace, or use
"Import file..." to add a .gguf you already have. Any .gguf dropped into
your models folder also shows up in the menu automatically.

GPU: NVIDIA cards use CUDA, everything else uses Vulkan. On Windows 10 the
CUDA runtime sets itself up automatically (no CUDA toolkit needed).

TROUBLESHOOTING:
- Window does not appear -> install WebView2 (winget install
  Microsoft.EdgeWebView2Runtime) or Python 3.10+.
- "Lemonade Server is not reachable" -> it starts automatically; if it
  still fails, reboot once.
- Pages take minutes -> normal on small GPUs; the 30B wants 16 GB+ VRAM.
- Port 5057 busy -> close the other AltVerse window first.
