"""Snakemake report plugin entrypoint for Metadata4Ing RO-Crate generation.

This module exposes the Snakemake report plugin settings and reporter class.
The reporter builds an intermediate provenance representation, serializes it to
JSON-LD/Turtle, packages it as an RO-Crate for the selected profile, and
validates the final crate.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase

from snakemake_report_plugin_metadata4ing.provenance import ProvenanceBuilder
from snakemake_report_plugin_metadata4ing.rocrate_builder import (
    DEFAULT_PROVENANCE_RUN_CRATE_DESCRIPTION,
    DEFAULT_PROVENANCE_RUN_CRATE_NAME,
    DEFAULT_RO_CRATE_LICENSE,
    PROVENANCE_RUN_CRATE_PROFILE,
    RO_CRATE_PROFILE,
    SUPPORTED_PROFILE_IDENTIFIERS,
    rocrate_builder_for_profile,
)
from snakemake_report_plugin_metadata4ing.utils import validate_filename
from snakemake_report_plugin_metadata4ing.validator import validate_rocrate


@dataclass
class ReportSettings(ReportSettingsBase):
    """User-configurable settings exposed through the Snakemake CLI.

    Attributes:
        paramscript: Optional path to a Python module implementing
            :class:`ParameterExtractorInterface`. When provided, the extractor is
            invoked for workflow files to derive additional parameter metadata.
        name: Top-level RO-Crate name.
        description: Top-level RO-Crate description.
        license: Top-level RO-Crate license.
        filename: Optional output filename stem for the generated crate ZIP. The
            ``.zip`` suffix is added automatically.
        profile: Identifier of the RO-Crate profile to emit. Supported
            values are defined in :mod:`snakemake_report_plugin_metadata4ing.rocrate_builder`.
    """

    paramscript: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Path to external Python script which implements the ParameterExtractorInterface.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )

    name: str = field(
        default=DEFAULT_PROVENANCE_RUN_CRATE_NAME,
        metadata={
            "help": "Top-level RO-Crate name.",
            "env_var": False,
            "required": False,
        },
    )

    description: str = field(
        default=DEFAULT_PROVENANCE_RUN_CRATE_DESCRIPTION,
        metadata={
            "help": "Top-level RO-Crate description.",
            "env_var": False,
            "required": False,
        },
    )

    license: str = field(
        default=DEFAULT_RO_CRATE_LICENSE,
        metadata={
            "help": "Top-level RO-Crate license.",
            "env_var": False,
            "required": False,
        },
    )

    filename: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Name of the file to be created for storing provenance.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )

    profile: str = field(
        default=PROVENANCE_RUN_CRATE_PROFILE,
        metadata={
            "help": (
                "RO-Crate profile to create. Supported values: "
                f"{RO_CRATE_PROFILE}, {PROVENANCE_RUN_CRATE_PROFILE}."
            ),
            "env_var": False,
            "required": False,
        },
    )


class Reporter(ReporterBase):
    """Snakemake report plugin that generates and validates RO-Crates.

    The reporter coordinates three stages:
    1. provenance extraction from Snakemake runtime objects,
    2. RO-Crate construction for the selected profile,
    3. validation of the generated crate.
    """

    provenance_filename = "provenance.jsonld"
    provenance_ttl_filename = "provenance.ttl"
    external_directory_name = "_EXTERNAL"

    def render(self):
        """Build provenance, package it as an RO-Crate, and validate it.

        Returns:
            None. The method writes output files as a side effect.

        Raises:
            ValueError: If the configured filename or profile is invalid.
            ROCrateValidationError: If the generated crate does not validate.
        """
        if self.settings.filename:
            validate_filename(str(self.settings.filename))

        profile_identifier = self._profile_identifier()
        self._render_rocrate(profile_identifier)

    def _profile_identifier(self) -> str:
        """Return the selected profile after validation.

        Returns:
            The normalized profile requested by the user.

        Raises:
            ValueError: If the configured profile is not supported.
        """
        profile_identifier = self.settings.profile or RO_CRATE_PROFILE
        if profile_identifier not in SUPPORTED_PROFILE_IDENTIFIERS:
            supported = ", ".join(sorted(SUPPORTED_PROFILE_IDENTIFIERS))
            raise ValueError(
                f"Unsupported profile '{profile_identifier}'. "
                f"Supported values are: {supported}."
            )
        return profile_identifier

    def _render_rocrate(self, profile_identifier: str) -> None:
        """Run the end-to-end provenance-to-RO-Crate pipeline.

        Args:
            profile_identifier: Target RO-Crate profile to build.

        Returns:
            None. The method writes provenance files and the final crate ZIP.

        Raises:
            ROCrateValidationError: If the generated crate fails validation.
        """
        provenance_builder = ProvenanceBuilder(
            jobs=self.jobs,
            dag=self.dag,
            settings=self.settings,
            provenance_filename=self.provenance_filename,
            provenance_ttl_filename=self.provenance_ttl_filename,
            external_directory_name=self.external_directory_name,
        )

        with provenance_builder.workspace():
            provenance = provenance_builder.build()
            provenance_builder.write_files(provenance)

            crate_builder = rocrate_builder_for_profile(
                profile_identifier=profile_identifier,
                settings=self.settings,
                provenance_filename=self.provenance_filename,
                provenance_ttl_filename=self.provenance_ttl_filename,
            )
            crate_path = crate_builder.write(provenance)
            validate_rocrate(crate_path, profile_identifier=profile_identifier)
