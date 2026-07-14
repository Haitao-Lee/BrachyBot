"""DoseUNet architecture used by the spacing-normalized dose checkpoint.

This module mirrors the training architecture in ``dose_tools``. Keeping the
architecture in the product avoids importing a training script at runtime and
makes checkpoint loading deterministic.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv3d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.InstanceNorm3d(out_channels, affine=True),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Conv3d(out_channels, out_channels, 3, padding=1, bias=False),
            nn.InstanceNorm3d(out_channels, affine=True),
            nn.LeakyReLU(0.1, inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class DoseUNet(nn.Module):
    """3D U-Net used by ``train_dose_model_spacing1mm``."""

    def __init__(self, in_channels: int = 3, out_channels: int = 1,
                 features=(16, 32, 64, 128, 256)):
        super().__init__()
        f = list(features)
        if len(f) != 5:
            raise ValueError(f"DoseUNet requires five feature widths, got {f}")

        self.enc0 = ConvBlock(in_channels, f[0])
        self.enc1 = ConvBlock(f[0], f[1])
        self.enc2 = ConvBlock(f[1], f[2])
        self.enc3 = ConvBlock(f[2], f[3])
        self.bottleneck = ConvBlock(f[3], f[4])

        self.up3 = nn.ConvTranspose3d(f[4], f[3], 2, stride=2)
        self.dec3 = ConvBlock(f[3] + f[3], f[3])
        self.up2 = nn.ConvTranspose3d(f[3], f[2], 2, stride=2)
        self.dec2 = ConvBlock(f[2] + f[2], f[2])
        self.up1 = nn.ConvTranspose3d(f[2], f[1], 2, stride=2)
        self.dec1 = ConvBlock(f[1] + f[1], f[1])
        self.up0 = nn.ConvTranspose3d(f[1], f[0], 2, stride=2)
        self.dec0 = ConvBlock(f[0] + f[0], f[0])

        self.out = nn.Conv3d(f[0], out_channels, 1)
        self.softplus = nn.Softplus()

    @staticmethod
    def pad_to_match(x: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        dz = target.shape[-3] - x.shape[-3]
        dy = target.shape[-2] - x.shape[-2]
        dx = target.shape[-1] - x.shape[-1]
        if dz == 0 and dy == 0 and dx == 0:
            return x
        if min(dx, dy, dz) < 0:
            raise ValueError(
                "DoseUNet decoder is larger than its skip connection: "
                f"decoder={tuple(x.shape[-3:])}, skip={tuple(target.shape[-3:])}"
            )
        return F.pad(x, [0, dx, 0, dy, 0, dz], mode="replicate")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e0 = self.enc0(x)
        e1 = self.enc1(F.max_pool3d(e0, 2))
        e2 = self.enc2(F.max_pool3d(e1, 2))
        e3 = self.enc3(F.max_pool3d(e2, 2))
        b = self.bottleneck(F.max_pool3d(e3, 2))

        d3 = self.pad_to_match(self.up3(b), e3)
        d3 = self.dec3(torch.cat([e3, d3], dim=1))
        d2 = self.pad_to_match(self.up2(d3), e2)
        d2 = self.dec2(torch.cat([e2, d2], dim=1))
        d1 = self.pad_to_match(self.up1(d2), e1)
        d1 = self.dec1(torch.cat([e1, d1], dim=1))
        d0 = self.pad_to_match(self.up0(d1), e0)
        d0 = self.dec0(torch.cat([e0, d0], dim=1))
        return self.softplus(self.out(d0))


__all__ = ["ConvBlock", "DoseUNet"]
