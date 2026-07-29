"""Download the gated BiomedParse v2 checkpoint into BrachyBot's model path.

The upstream checkpoint requires an authenticated Hugging Face account with
the model terms accepted. It is intentionally not downloaded during server
startup and is ignored by Git because it is a large binary.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


REPO_ID = "microsoft/BiomedParse"
FILENAME = "biomedparse_v2.ckpt"
TEXT_REPO_ID = "openai/clip-vit-base-patch32"
TEXT_ASSET_FILES = (
    "config.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)
DEFAULT_DESTINATION = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "ctv"
    / "biomedparse_v2"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help="Directory that will contain biomedparse_v2.ckpt.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional Hugging Face token; HF_TOKEN is used when omitted.",
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "Install the downloader first: pip install huggingface_hub"
        ) from exc

    token = args.token or os.environ.get("HF_TOKEN") or os.environ.get(
        "HUGGINGFACEHUB_API_TOKEN"
    )
    if not token:
        raise SystemExit(
            "BiomedParse is gated. Set HF_TOKEN after accepting the model terms "
            "at https://huggingface.co/microsoft/BiomedParse, then rerun."
        )

    args.destination.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=str(args.destination),
        token=token,
    )
    print(f"Downloaded BiomedParse v2 checkpoint to: {downloaded}")
    text_destination = args.destination / "clip-vit-base-patch32"
    text_destination.mkdir(parents=True, exist_ok=True)
    for filename in TEXT_ASSET_FILES:
        downloaded_asset = hf_hub_download(
            repo_id=TEXT_REPO_ID,
            filename=filename,
            local_dir=str(text_destination),
            token=token,
        )
        print(f"Downloaded BiomedParse text asset to: {downloaded_asset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
