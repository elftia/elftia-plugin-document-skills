"""Optional callable .NET OpenXML enhancement provider.

Module provenance: original Elftia-authored clean-room implementation.
This package is a consulted enhancement provider behind the existing
composite dispatch; it is NEVER agent-visible, NEVER auto-installed, and
NEVER executes macros/DDE/external-data-refresh.
"""

from .service import build_dotnet_provider

__all__ = ["build_dotnet_provider"]
