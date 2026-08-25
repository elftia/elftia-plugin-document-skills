"""Shared operation-wide budgets for bounded PDF image extraction."""

from dataclasses import dataclass

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

MAX_TOTAL_IMAGE_PIXELS = 100_000_000


@dataclass
class ImageExtractionBudget:
    """Track count, pixels, inline samples, and encoded output across one operation."""

    max_images: int
    max_output_bytes: int
    max_pixels: int = MAX_TOTAL_IMAGE_PIXELS
    image_count: int = 0
    total_pixels: int = 0
    total_output_bytes: int = 0
    total_inline_sample_bytes: int = 0

    def reserve_image(
        self,
        width: int,
        height: int,
        *,
        inline_sample_bytes: int = 0,
    ) -> None:
        if self.image_count >= self.max_images:
            _unsafe(
                "Extracted image count exceeds the caller-selected limit.",
                limit=self.max_images,
            )
        pixels = width * height
        next_pixels = self.total_pixels + pixels
        if next_pixels > self.max_pixels:
            _unsafe(
                "Extracted image pixels exceed the aggregate safety limit.",
                pixels=next_pixels,
                limit=self.max_pixels,
            )
        next_samples = self.total_inline_sample_bytes + inline_sample_bytes
        max_samples = self.max_pixels * 3
        if next_samples > max_samples:
            _unsafe(
                "Inline image samples exceed the aggregate safety limit.",
                bytes=next_samples,
                limit=max_samples,
            )
        self.image_count += 1
        self.total_pixels = next_pixels
        self.total_inline_sample_bytes = next_samples

    def add_output_bytes(self, byte_count: int) -> None:
        next_total = self.total_output_bytes + byte_count
        if next_total > self.max_output_bytes:
            _unsafe(
                "Extracted image bytes exceed the caller-selected limit.",
                bytes=next_total,
                limit=self.max_output_bytes,
            )
        self.total_output_bytes = next_total


def _unsafe(message: str, **details: int) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
