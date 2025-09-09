import json
import os
from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)
import yaml
import subprocess

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
                        "unit": f"units:{val["unit"] }" if "unit" in val else None,
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

    def extract_tools(self, rule_name: str, env_file_content: str) -> dict:
        targets = {"fenics-dolfinx", "KratosMultiphysics-all"}
        results = {}
        found_targets = set()

        parsed = yaml.safe_load(env_file_content)
        dependencies = parsed.get("dependencies", [])
        
        for dep in dependencies:
            if isinstance(dep, str):
                for target in targets:
                    if dep.strip().lower().startswith(target.lower()):
                        found_targets.add(target)
            elif isinstance(dep, dict):
                for _, pkgs in dep.items():
                    for pkg in pkgs:
                        for target in targets:
                            if pkg.strip().lower().startswith(target.lower()):
                                found_targets.add(target)

        envs = self._list_conda_envs()

        for env_name, env_path in envs.items():
            try:
                pkgs = self._get_packages(env_path, found_targets)
            except Exception as e:
                print(f"[Warning] Could not get packages for {env_name}: {e}")
                continue

            found = found_targets.intersection(pkgs.keys())
            for pkg in found:
                results[pkg] = pkgs[pkg]

        return results

    def _get_type(self, val):
        if isinstance(val, float):
            return "schema:Float"
        elif isinstance(val, int):
            return "schema:Integer"
        elif isinstance(val, str):
            return "schema:Text"
        return None
    
    def _list_conda_envs(self):
        """Return a dict {env_name: env_path} of all conda environments."""
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True, text=True, check=True
        )
        envs_info = json.loads(result.stdout)
        return {path.split("/")[-1]: path for path in envs_info["envs"]}

    def _get_packages(self, env_path, targets):
        """Return dict {package: version} for given env path."""
        result = subprocess.run(
            ["conda", "list", "--prefix", env_path, "--json"],
            capture_output=True, text=True, check=True
        )
        all_packages = json.loads(result.stdout)
        return {pkg["name"]: pkg["version"] for pkg in all_packages if pkg["name"] in targets}