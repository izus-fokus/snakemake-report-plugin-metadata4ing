import json
import re
import subprocess
import yaml


class ReporterTools:
    def _extract_tools_from_yaml(self, env_file_content: str) -> dict:
        results = {}
        found_targets = set()
        parsed = yaml.safe_load(env_file_content)
        dependencies = parsed.get("dependencies", [])

        version_pattern = re.compile(r"([a-zA-Z0-9_.\-]+)([=><!~]+.*)?")

        # Parse YAML dependencies
        for dep in dependencies:
            if isinstance(dep, str):
                match = version_pattern.match(dep.strip())
                if match:
                    pkg_name = match.group(1).lower()
                    version = (
                        match.group(2).lstrip("=") if match.group(2) else None
                    )
                    results[pkg_name] = version
                    found_targets.add(pkg_name)
            elif isinstance(dep, dict):
                for _, pkgs in dep.items():
                    for pkg in pkgs:
                        match = version_pattern.match(pkg.strip())
                        if match:
                            pkg_name = match.group(1).lower()
                            version = (
                                match.group(2).lstrip("=")
                                if match.group(2)
                                else None
                            )
                            results[pkg_name] = version
                            found_targets.add(pkg_name)

        envs = self._list_conda_envs()

        # Find the first env that contains all target packages
        selected_env_pkgs = None
        for _, env_path in envs.items():
            try:
                pkgs = self._get_packages(env_path, found_targets)
            except Exception:
                continue

            if all(pkg in pkgs for pkg in found_targets):
                selected_env_pkgs = pkgs
                break  # Stop at the first matching environment

        # Fill in missing versions from the selected environment
        if selected_env_pkgs:
            for pkg in found_targets:
                if results.get(pkg) is None and pkg in selected_env_pkgs:
                    results[pkg] = selected_env_pkgs[pkg]

        return results

    def _add_tools(self, env_file_content: str) -> list:
        tools_list = []
        tools = self._extract_tools_from_yaml(env_file_content)
        if tools:
            for name, version in tools.items():
                if name not in self.tools_dict:
                    item = {
                        "@id": f"local:tool_{self.tool_counter}",
                        "@type": "schema:SoftwareApplication",
                        "label": name,
                        **({"softwareVersion": version} if version else {}),
                    }
                    self.tools_dict[name] = item
                    self.tool_counter += 1
                    tools_list.append(item)
                else:
                    tools_list.append(self.tools_dict[name])
        return tools_list

    def _list_conda_envs(self):
        """Return a dict {env_name: env_path} of all conda environments."""
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        envs_info = json.loads(result.stdout)
        return {path.split("/")[-1]: path for path in envs_info["envs"]}

    def _get_packages(self, env_path, targets):
        """Return dict {package: version} for given env path."""
        result = subprocess.run(
            ["conda", "list", "--prefix", env_path, "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        all_packages = json.loads(result.stdout)
        return {
            pkg["name"]: pkg["version"]
            for pkg in all_packages
            if pkg["name"].lower() in targets
        }
