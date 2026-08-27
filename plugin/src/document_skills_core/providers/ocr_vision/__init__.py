"""Optional OCR/vision provider for layered PPTX reconstruction."""

from .provider import ObservationAdapter, build_ocr_vision_provider

__all__ = ["ObservationAdapter", "build_ocr_vision_provider"]
