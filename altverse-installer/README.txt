AltVerse Browser - local AI alternate-universe browser
====================================================

INSTALL: run AltVerseSetup.exe, pick a model on the AI Model page
(models already downloaded on your PC are listed there), keep
"Download the AI model now" checked, and it launches by itself.
Two clicks, then everything works.

WHAT YOU NEED: almost nothing.
Python and Lemonade Server install themselves during setup
(approve the admin prompts). Then it downloads the model and launches.
3. Internet - first launch downloads the AI model:
   Poor mans AI (4B)  = ~2.4 GB download
   Nice 30B           = ~17 GB download
4. Windows 11 recommended (the CUDA backend needs it).
   NVIDIA GPU required.

HOW TO USE:
Double-click the "AltVerse Browser" desktop shortcut.
Pick pages, click links, go down the rabbit hole.
Close the browser window and the server quits too (Chrome version).

CHANGE YOUR MIND ABOUT THE MODEL LATER:
Open model.txt in the install folder. Line 1 = model id, line 2 = ctx size.
  Poor mans AI:  Qwen3-4B-Instruct-2507-GGUF  +  4096
  Nice 30B:      Qwen3-Coder-30B-A3B-Instruct-Q4_K_M  +  8192
Save the file and launch again. The model downloads on first use.

TROUBLESHOOTING:
- "lemonade: command not found" -> install Lemonade Server (step 2).
- GPU backend is picked automatically: NVIDIA cards use CUDA,
  anything else uses Vulkan (works on AMD, Intel, older cards).
- Pages take minutes -> normal on small GPUs; the 30B wants 16GB+ VRAM.
- Port 5057 busy -> close the other AltVerse window first.
