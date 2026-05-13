"""Software tool discovery from conda environment definitions."""

import json
import re
import subprocess

import yaml


class ToolResolver:
    """Resolve software tool metadata from conda environment definitions.

    Tool versions can be declared directly in a workflow's environment YAML,
    but sometimes only package names are present. This helper inspects local
    conda environments to fill in missing versions when possible.
    """

    def __init__(self) -> None:
        """Initialize conda discovery caches.

        Returns:
            None.
        """
        self._envs: dict[str, str] | None = None
        self._packages_by_env: dict[str, dict[str, str]] = {}

    def extract_tools_from_yaml(self, env_file_content: str) -> dict[str, str | None]:
        """Extract tool names and versions from a conda environment file.

        Args:
            env_file_content: Text contents of a conda environment YAML file.

        Returns:
            dict[str, str | None]: Mapping from normalized package name to
            discovered version. Versions remain ``None`` when neither the YAML
            file nor the inspected local environments provide one.
        """
        results: dict[str, str | None] = {}
        found_targets = set()
        parsed = yaml.safe_load(env_file_content) or {}
        dependencies = parsed.get("dependencies", [])

        version_pattern = re.compile(r"([a-zA-Z0-9_.\-]+)([=><!~]+.*)?")

        for dep in dependencies:
            if isinstance(dep, str):
                match = version_pattern.match(dep.strip())
                if not match:
                    continue
                pkg_name = match.group(1).lower()
                version = match.group(2).lstrip("=") if match.group(2) else None
                results[pkg_name] = version
                found_targets.add(pkg_name)
            elif isinstance(dep, dict):
                for _, pkgs in dep.items():
                    for pkg in pkgs:
                        match = version_pattern.match(pkg.strip())
                        if not match:
                            continue
                        pkg_name = match.group(1).lower()
                        version = (
                            match.group(2).lstrip("=") if match.group(2) else None
                        )
                        results[pkg_name] = version
                        found_targets.add(pkg_name)

        selected_env_pkgs = None
        for _, env_path in self._list_conda_envs().items():
            try:
                pkgs = self._get_packages(env_path, found_targets)
            except Exception:
                continue
            if all(pkg in pkgs for pkg in found_targets):
                selected_env_pkgs = pkgs
                break

        if selected_env_pkgs:
            for pkg in found_targets:
                if results.get(pkg) is None and pkg in selected_env_pkgs:
                    results[pkg] = selected_env_pkgs[pkg]

        return results

    def _list_conda_envs(self) -> dict[str, str]:
        """List locally available conda environments.

        Returns:
            dict[str, str]: Mapping from environment name to environment path.

        Raises:
            subprocess.CalledProcessError: If ``conda env list --json`` fails.
            json.JSONDecodeError: If the command output is not valid JSON.
        """
        if self._envs is None:
            result = subprocess.run(
                ["conda", "env", "list", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            envs_info = json.loads(result.stdout)
            self._envs = {path.split("/")[-1]: path for path in envs_info["envs"]}
        return self._envs

    def _get_packages(self, env_path: str, targets: set[str]) -> dict[str, str]:
        """Return package versions for selected packages in one environment.

        Args:
            env_path: Filesystem path to the conda environment to inspect.
            targets: Lower-cased package names to keep in the returned mapping.

        Returns:
            dict[str, str]: Mapping from package name to installed version for
            the subset present in ``targets``.

        Raises:
            subprocess.CalledProcessError: If ``conda list --json`` fails.
            json.JSONDecodeError: If the command output is not valid JSON.
        """
        if env_path not in self._packages_by_env:
            result = subprocess.run(
                ["conda", "list", "--prefix", env_path, "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            all_packages = json.loads(result.stdout)
            self._packages_by_env[env_path] = {
                pkg["name"]: pkg["version"] for pkg in all_packages
            }
        return {
            pkg_name: version
            for pkg_name, version in self._packages_by_env[env_path].items()
            if pkg_name.lower() in targets
        }
