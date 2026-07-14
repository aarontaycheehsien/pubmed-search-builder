"""Runtime architecture for the PubMed Search Builder skill.

The package is deliberately standard-library only.  The command files in
``scripts/`` remain stable compatibility adapters while new workflow features
are implemented here.
"""

from .workflow.contracts import ARTIFACT_ENVELOPE_VERSION

__all__ = ("ARTIFACT_ENVELOPE_VERSION",)
