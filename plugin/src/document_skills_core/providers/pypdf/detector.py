"""Exact-version and functional detector for the accepted pypdf provider."""

from io import BytesIO

from document_skills_core.core.capabilities import DetectionEvidence

EXPECTED_PYPDF_VERSION = "6.16.2"
EXPECTED_CRYPTOGRAPHY_VERSION = "50.0.0"
EXPECTED_PILLOW_VERSION = "12.3.0"


def detect_pypdf() -> DetectionEvidence:
    try:
        import cryptography
        import pypdf
        from PIL import __version__ as pillow_version
    except ModuleNotFoundError:
        return DetectionEvidence(
            False,
            reason="The locked pypdf AES runtime is not installed.",
        )
    pypdf_version = pypdf.__version__
    cryptography_version = cryptography.__version__
    if pypdf_version != EXPECTED_PYPDF_VERSION:
        return DetectionEvidence(
            False,
            version=pypdf_version,
            reason="The installed pypdf version does not match policy.",
        )
    if cryptography_version != EXPECTED_CRYPTOGRAPHY_VERSION:
        return DetectionEvidence(
            False,
            version=pypdf_version,
            reason="The installed cryptography version does not match policy.",
        )
    if pillow_version != EXPECTED_PILLOW_VERSION:
        return DetectionEvidence(
            False,
            version=pypdf_version,
            reason="The installed Pillow version does not match PDF compression policy.",
        )
    try:
        payload = BytesIO()
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.encrypt(
            "provider-probe-user",
            "provider-probe-owner",
            algorithm="AES-256-R5",
        )
        writer.write(payload)
        reader = pypdf.PdfReader(BytesIO(payload.getvalue()), strict=True)
        if not reader.is_encrypted or reader.decrypt("provider-probe-user") == 0:
            raise ValueError("AES round-trip failed")
        if len(reader.pages) != 1:
            raise ValueError("AES round-trip page mismatch")
    except Exception:
        return DetectionEvidence(
            False,
            version=pypdf_version,
            reason="The locked pypdf AES functional probe failed.",
        )
    return DetectionEvidence(True, version=pypdf_version)


def pypdf_diagnostics() -> dict[str, str]:
    import cryptography
    import pypdf
    from PIL import __version__ as pillow_version

    return {
        "pypdf": pypdf.__version__,
        "cryptography": cryptography.__version__,
        "pillow": pillow_version,
    }
