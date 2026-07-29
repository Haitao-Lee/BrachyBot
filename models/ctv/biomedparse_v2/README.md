# BiomedParse v2 deployment directory

Place the authenticated upstream `biomedparse_v2.ckpt` file in this directory.
The binary is intentionally ignored by Git because it is large and the
Hugging Face repository is gated. The same downloader also stores the official
CLIP tokenizer assets under `clip-vit-base-patch32`, allowing inference without
a first-request network download. From the repository root, run:

```powershell
$env:HF_TOKEN = "<your Hugging Face access token>"
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
python scripts\download_biomedparse_v2.py
```

The official BiomedParse v2 checkout and its isolated dependencies are still
required. Configure `BIOMEDPARSE_ROOT` to that checkout before starting the
server. The BrachyBot adapter will discover the checkpoint here unless
`BIOMEDPARSE_V2_CHECKPOINT` explicitly points elsewhere. It discovers the
tokenizer subdirectory unless `BIOMEDPARSE_V2_TEXT_ASSETS` is configured.
