import json
import os
from snakemake_report_plugin_metadat4ing.interfaces import ParameterExtractorInterface

class ParameterExtractor(ParameterExtractorInterface):
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        results = {}
        file_name = os.path.basename(file_path)
        if file_name.startswith("parameters_") and rule_name == "generate_input_files":
            with open(file_path) as f:
                data = json.load(f)
            for key, val in data.items():
                if isinstance(val, dict):
                    results[key] = {
                        'value': val['value'],
                        'unit': self._get_unit(key),
                        'json-path': f"/{key}/value",
                        'data-type': self._get_type(val['value'])
                    }
                else:
                    results[key] = {
                        'value': val,
                        'unit': None,
                        'json-path': f"/{key}",
                        'data-type': self._get_type(val)
                    }
        return results

    def _get_unit(self, name: str):
        return {
            "young-modulus": "units:PA",
            "load": "units:MegaPA",
            "length": "units:m",
            "radius": "units:m",
            "element-size": "units:m"
        }.get(name)

    def _get_type(self, val):
        if isinstance(val, float):
            return "schema:Float"
        elif isinstance(val, int):
            return "schema:Integer"
        elif isinstance(val, str):
            return "schema:Text"
        return None
