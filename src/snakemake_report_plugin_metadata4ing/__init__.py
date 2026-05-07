import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase

from snakemake_report_plugin_metadata4ing.create_provenance import (
    create_provenance_run_rocrate,
)
from snakemake_report_plugin_metadata4ing.provenance import ProvenanceBuilder
from snakemake_report_plugin_metadata4ing.rocrate_builder import (
    Metadata4IngROCrateBuilder,
)
from snakemake_report_plugin_metadata4ing.utils import validate_filename

RO_CRATE_PROFILE = "ro-crate-1.1"
PROVENANCE_RUN_CRATE_PROFILE = "provenance-run-crate-0.5"
SUPPORTED_PROFILE_IDENTIFIERS = {
    RO_CRATE_PROFILE,
    PROVENANCE_RUN_CRATE_PROFILE,
}


@dataclass
class ReportSettings(ReportSettingsBase):
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

    config: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Config file in JSON format containing metadata about the research problem.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
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

    profile_identifier: str = field(
        default=PROVENANCE_RUN_CRATE_PROFILE,#RO_CRATE_PROFILE,
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
    provenance_filename = "provenance.jsonld"
    provenance_ttl_filename = "provenance.ttl"
    external_directory_name = "_EXTERNAL"

    def render(self):
        if self.settings.filename:
            validate_filename(str(self.settings.filename))

        profile_identifier = self._profile_identifier()
        config_data = self._read_config()
        if profile_identifier == PROVENANCE_RUN_CRATE_PROFILE:
            self._render_provenance_run_crate(config_data)
            return

        self._render_metadata4ing_rocrate(config_data)

    def _profile_identifier(self) -> str:
        profile_identifier = self.settings.profile_identifier or RO_CRATE_PROFILE
        if profile_identifier not in SUPPORTED_PROFILE_IDENTIFIERS:
            supported = ", ".join(sorted(SUPPORTED_PROFILE_IDENTIFIERS))
            raise ValueError(
                f"Unsupported profile_identifier '{profile_identifier}'. "
                f"Supported values are: {supported}."
            )
        return profile_identifier

    def _render_metadata4ing_rocrate(self, config_data: dict) -> None:
        provenance_builder = ProvenanceBuilder(
            jobs=self.jobs,
            dag=self.dag,
            settings=self.settings,
            config_data=config_data,
            provenance_filename=self.provenance_filename,
            provenance_ttl_filename=self.provenance_ttl_filename,
            external_directory_name=self.external_directory_name,
        )

        provenance_builder.create_external_directory()
        try:
            provenance = provenance_builder.build()
            provenance_builder.write_files(provenance)

            crate_builder = Metadata4IngROCrateBuilder(
                settings=self.settings,
                config_data=config_data,
                provenance_filename=self.provenance_filename,
                provenance_ttl_filename=self.provenance_ttl_filename,
            )
            crate_builder.write(provenance)
        finally:
            provenance_builder.clean_data()

    def _render_provenance_run_crate(self, config_data: dict) -> None:
        provenance_builder = ProvenanceBuilder(
            jobs=self.jobs,
            dag=self.dag,
            settings=self.settings,
            config_data=config_data,
            provenance_filename=self.provenance_filename,
            provenance_ttl_filename=self.provenance_ttl_filename,
            external_directory_name=self.external_directory_name,
        )

        provenance_builder.create_external_directory()
        try:
            provenance = provenance_builder.build()
            provenance_builder.write_files(provenance)
            create_provenance_run_rocrate(
                provenance=provenance,
                config_data=config_data,
                provenance_filename=self.provenance_filename,
                provenance_ttl_filename=self.provenance_ttl_filename,
                output_path=self._crate_output_path("RO"),
            )
        finally:
            provenance_builder.clean_data()

    def _crate_output_path(self, default_stem: str) -> Path:
        if self.settings.filename:
            return Path(f"{self.settings.filename}.zip")
        return Path(f"{default_stem}.zip")

    def _read_config(self):
        if not self.settings.config:
            return {}

        config_path = Path(self.settings.config).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Error parsing JSON config file: {e}") from e
