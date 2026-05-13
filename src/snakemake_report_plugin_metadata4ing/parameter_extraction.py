"""Optional user-provided parameter extractor loading and validation."""

import importlib.util
import inspect
from pathlib import Path
from typing import Any

from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)


class ParameterExtractorRunner:
    """Load and execute an optional external parameter-extractor script.

    The plugin allows users to provide a Python script implementing
    :class:`ParameterExtractorInterface`. This wrapper imports that script once,
    instantiates the first matching implementation, executes it for relevant
    files, and validates the returned metadata shape.
    """

    def __init__(self, script_path: Path | None) -> None:
        """Store the extractor path and initialize the lazy instance cache.

        Args:
            script_path: Path to the user-provided Python module containing a
                ``ParameterExtractorInterface`` implementation, or ``None`` if
                parameter extraction is disabled.

        Returns:
            None.
        """
        self.script_path = script_path.expanduser().resolve() if script_path else None
        self._extractor = None

    @property
    def enabled(self) -> bool:
        """Return whether parameter extraction is enabled.

        Returns:
            bool: ``True`` when a script path was configured, otherwise
            ``False``.
        """
        return self.script_path is not None

    def extract(self, rule_name: str, file_path: str) -> dict[str, Any]:
        """Run the configured extractor for one rule/file pair.

        Args:
            rule_name: Name of the Snakemake rule currently being processed.
            file_path: Path to the file whose contents may contain parameter
                metadata.

        Returns:
            dict[str, Any]: Validated extractor output. An empty dictionary is
            returned when extraction is disabled or the extractor returns a
            falsey result.

        Raises:
            FileNotFoundError: If extraction is enabled but the configured
                script path does not exist.
            ImportError: If the script cannot provide a valid extractor class.
            TypeError: If the extractor output has the wrong container types.
            ValueError: If required extractor keys are missing.
        """
        if not self.enabled:
            return {}
        extractor = self._load_extractor()
        result = extractor.extract_params(rule_name, file_path)
        return self.validate_output(result) if result else {}

    def _load_extractor(self):
        """Import and instantiate the configured extractor implementation.

        Returns:
            ParameterExtractorInterface: Instantiated extractor implementation.

        Raises:
            FileNotFoundError: If the configured script path does not exist.
            ImportError: If the module does not define a concrete subclass of
                ``ParameterExtractorInterface``.
        """
        if self._extractor is not None:
            return self._extractor
        if self.script_path is None or not self.script_path.exists():
            raise FileNotFoundError(f"Script not found: {self.script_path}")

        spec = importlib.util.spec_from_file_location(
            "extractor_module", str(self.script_path)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ParameterExtractorInterface)
                and obj is not ParameterExtractorInterface
            ):
                self._extractor = obj()
                return self._extractor

        raise ImportError("No subclass of ParameterExtractorInterface found in script")

    @staticmethod
    def validate_output(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the structure returned by a parameter extractor.

        The expected shape is::

            {
                "<processing-step-name>": {
                    "has parameter": [
                        {"<name>": {"value": ..., "unit": ..., ...}}
                    ],
                    "investigates": [...]
                }
            }

        Args:
            result: Raw dictionary returned by the extractor implementation.

        Returns:
            dict[str, Any]: The same dictionary when validation succeeds.

        Raises:
            TypeError: If keys or values have unexpected types.
            ValueError: If required sections or required per-parameter keys are
                missing.
        """
        if not isinstance(result, dict):
            raise TypeError("Function output must be a dictionary.")

        def _validate_entry(entry_key, entry_value):
            if not isinstance(entry_key, str):
                raise TypeError(f"Key '{entry_key}' must be a string.")
            if not isinstance(entry_value, dict):
                raise TypeError(
                    f"Value for key '{entry_key}' must be a dictionary."
                )

            required_keys = ["value", "unit", "json-path", "data-type"]
            for required_key in required_keys:
                if required_key not in entry_value:
                    raise ValueError(
                        f"Missing key '{required_key}' in value for '{entry_key}'."
                    )

            if entry_value["unit"] and not isinstance(entry_value["unit"], str):
                raise TypeError(f"'unit' for '{entry_key}' must be a string.")
            if not isinstance(entry_value["json-path"], str):
                raise TypeError(f"'json-path' for '{entry_key}' must be a string.")
            if not isinstance(entry_value["data-type"], str):
                raise TypeError(f"'data-type' for '{entry_key}' must be a string.")

        def _validate_section(section_name, section_content):
            if not isinstance(section_content, list):
                raise TypeError(f"'{section_name}' must be a list.")
            for item in section_content:
                if not isinstance(item, dict):
                    raise TypeError(
                        f"Each item in '{section_name}' must be a dictionary."
                    )
                if len(item) != 1:
                    raise ValueError(
                        f"Each item in '{section_name}' must have exactly one "
                        f"key, found {len(item)}."
                    )
                inner_key, inner_value = next(iter(item.items()))
                _validate_entry(inner_key, inner_value)

        for root_key, root_value in result.items():
            if not isinstance(root_key, str):
                raise TypeError(f"Root key '{root_key}' must be a string.")
            if not isinstance(root_value, dict):
                raise TypeError(
                    f"Root value for '{root_key}' must be a dictionary."
                )

            if not any(
                key in root_value for key in ["has parameter", "investigates"]
            ):
                raise ValueError(
                    f"Root key '{root_key}' must contain at least "
                    "'has parameter' or 'investigates'."
                )

            for section in ["has parameter", "investigates"]:
                if section in root_value:
                    _validate_section(section, root_value[section])

        return result
