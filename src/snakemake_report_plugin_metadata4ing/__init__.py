import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase

from snakemake_report_plugin_metadata4ing.provenance import ProvenanceBuilder
from snakemake_report_plugin_metadata4ing.rocrate_builder import (
    Metadata4IngROCrateBuilder,
)
from snakemake_report_plugin_metadata4ing.utils import validate_filename


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


class Reporter(ReporterBase):
    provenance_filename = "provenance.jsonld"
    provenance_ttl_filename = "provenance.ttl"
    external_directory_name = "_EXTERNAL"

    def render(self):
        if self.settings.filename:
            validate_filename(str(self.settings.filename))

        config_data = self._read_config()

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
