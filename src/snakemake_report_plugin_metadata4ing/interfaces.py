"""Interfaces implemented by optional plugin extension points.

The plugin currently exposes a single extension contract for parameter
extraction scripts. External scripts are loaded dynamically and must implement
the abstract methods defined here.
"""

from abc import ABC, abstractmethod


class ParameterExtractorInterface(ABC):
    """Protocol for external parameter extraction scripts.

    Implementations inspect a workflow rule and one of its associated files and
    return structured metadata describing parameters or investigated quantities.
    """

    @abstractmethod
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        """Return extracted parameter metadata for a rule/file pair.

        Args:
            rule_name: Name of the Snakemake rule being processed.
            file_path: Path to an input or output file associated with the rule.

        Returns:
            A dictionary in the schema expected by
            :meth:`ParameterExtractorRunner.validate_output`.
        """
        ...
