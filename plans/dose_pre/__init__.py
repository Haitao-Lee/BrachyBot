"""DoseUNet preprocessing package.

The package intentionally keeps imports lazy: model loading is optional until
the dose engine is requested, which keeps segmentation and report tools usable
in environments without PyTorch.
"""
