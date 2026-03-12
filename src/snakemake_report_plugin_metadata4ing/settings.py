from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from snakemake_interface_report_plugins.settings import ReportSettingsBase


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

    benchmarkfile: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Path to the benchmark file, which contains metadata about the research problem.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )

    configname: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Name of the config which is currently running",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )
