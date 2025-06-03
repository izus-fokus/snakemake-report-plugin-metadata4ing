import json
import os
from snakemake_report_plugin_metadat4ing.interfaces import (
    ParameterExtractorInterface,
)
import yaml
import re

class ParameterExtractor(ParameterExtractorInterface):
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        results = {}
        file_name = os.path.basename(file_path)
        if (
            file_name.startswith("parameters_")
            and rule_name == "generate_input_files"
        ):
            with open(file_path) as f:
                data = json.load(f)
            for key, val in data.items():
                if isinstance(val, dict):
                    results[key] = {
                        "value": val["value"],
                        "unit": self._get_unit(key),
                        "json-path": f"/{key}/value",
                        "data-type": self._get_type(val["value"]),
                    }
                else:
                    results[key] = {
                        "value": val,
                        "unit": None,
                        "json-path": f"/{key}",
                        "data-type": self._get_type(val),
                    }
        elif (
            file_name.startswith("summary_")
            and rule_name == "summary"
        ):
            with open(file_path) as f:
                data = json.load(f)
            for key, val in data.items():
                if key == "max_mises_stress":
                    results[key] = {
                        "value": val,
                        "unit": None,
                        "json-path": f"/{key}",
                        "data-type": "schema:Float",
                    }
        return results

    def extract_tools(self, rule_name: str, env_file_content: str,) -> dict:
        results = {}
        parsed = yaml.safe_load(env_file_content)
        dependencies = parsed.get("dependencies", [])

        for dep in dependencies:
            match = re.match(r'^([a-zA-Z0-9_\-]+)([=<>!].*)?$', dep)
            if match:
                name, version = match.groups()
                results[name] = version if version else None
        return results

    def _get_unit(self, name: str):
        return {
            "young-modulus": "units:PA",
            "load": "units:MegaPA",
            "length": "units:m",
            "radius": "units:m",
            "element-size": "units:m",
        }.get(name)

    def _get_type(self, val):
        if isinstance(val, float):
            return "schema:Float"
        elif isinstance(val, int):
            return "schema:Integer"
        elif isinstance(val, str):
            return "schema:Text"
        return None
