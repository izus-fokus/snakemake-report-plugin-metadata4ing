import json
import os
from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)

class ParameterExtractor(ParameterExtractorInterface):
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        results = {}
        file_name = os.path.basename(file_path)
        if (
            file_name.startswith("parameters_")
            and rule_name == "generate_input_files"
        ):
            results.setdefault("generate_input_files", {}).setdefault("has parameter", [])
            with open(file_path) as f:
                data = json.load(f)
            for key, val in data.items():
                if isinstance(val, dict):
                    results["generate_input_files"]["has parameter"].append({key: {
                        "value": val["value"],
                        "unit": f"{val["unit"]}" if "unit" in val else None,
                        "json-path": f"/{key}/value",
                        "data-type": self._get_type(val["value"]),
                    }})
                else:
                    results["generate_input_files"]["has parameter"].append({key: {
                        "value": val,
                        "unit": None,
                        "json-path": f"/{key}",
                        "data-type": self._get_type(val),
                    }})
        elif (
            file_name.startswith("summary_")
            and rule_name == "summary"
        ):
            results.setdefault("summary", {}).setdefault("investigates", [])
            with open(file_path) as f:
                data = json.load(f)
            for key, val in data.items():
                if key == "max_mises_stress":
                    results["summary"]["investigates"].append({key: {
                        "value": val,
                        "unit": None,
                        "json-path": f"/{key}",
                        "data-type": "schema:Float",
                    }})
        return results

    def _get_type(self, val):
        if isinstance(val, float):
            return "schema:Float"
        elif isinstance(val, int):
            return "schema:Integer"
        elif isinstance(val, str):
            return "schema:Text"
        return None