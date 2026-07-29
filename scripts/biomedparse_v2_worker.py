"""Isolated BiomedParse v2 inference worker.

The official v2 stack pins Python 3.10 and a CUDA/Detectron2 dependency set
that should not be installed into BrachyBot's web-server environment. This
worker receives a pre-windowed CT volume, performs the official inference
path, and returns one binary candidate mask.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

import numpy as np


def run(args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser().resolve()
    checkpoint = Path(args.checkpoint).expanduser().resolve()
    text_assets = Path(args.text_assets).expanduser().resolve()
    sys.path.insert(0, str(root))

    # Third-party initialization is noisy. Keep stdout available for future
    # machine protocols and route setup chatter to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        import hydra
        import torch
        import torch.nn.functional as F
        from hydra import compose
        from hydra.core.global_hydra import GlobalHydra
        from inference import merge_multiclass_masks, postprocess
        from utils import process_input, process_output

        GlobalHydra.instance().clear()
        with hydra.initialize_config_dir(
            config_dir=str(root / "configs" / "model"),
            job_name="brachybot_biomedparse_v2",
            version_base=None,
        ):
            cfg = compose(config_name="biomedparse_3D")
        cfg.sem_seg_head.predictor.language_encoder.tokenizer.pretrained_model_name_or_path = (
            str(text_assets)
        )
        model = hydra.utils.instantiate(cfg, _convert_="object")
        model.load_pretrained(str(checkpoint))
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device).eval()

        volume = np.load(args.input, allow_pickle=False)
        prepared, pad_width, padded_size, valid_axis = process_input(volume, 512)
        prepared = prepared.to(device).int()
        with torch.inference_mode():
            output = model(
                {"image": prepared.unsqueeze(0), "text": [args.prompt]},
                mode="eval",
                slice_batch_size=max(1, int(args.slice_batch_size)),
            )
            predictions = output["predictions"]
            mask_logits = F.interpolate(
                predictions["pred_gmasks"],
                size=(512, 512),
                mode="bicubic",
                align_corners=False,
                antialias=True,
            )
            masks = postprocess(mask_logits, predictions["object_existence"])
            mask_volume = merge_multiclass_masks(masks, [1])
            mask_array = process_output(
                mask_volume,
                pad_width,
                padded_size,
                valid_axis,
            )
            confidence = float(
                predictions["object_existence"].sigmoid().max().detach().cpu().item()
            )

    mask_array = (np.asarray(mask_array) > 0).astype(np.uint8, copy=False)
    np.save(args.output, mask_array, allow_pickle=False)
    Path(args.metadata).write_text(
        json.dumps(
            {
                "object_existence_confidence": confidence,
                "shape": list(mask_array.shape),
                "voxel_count": int(np.count_nonzero(mask_array)),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--text-assets", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--slice-batch-size", type=int, default=4)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
