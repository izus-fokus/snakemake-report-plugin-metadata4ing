"""File and supplemental-resource helpers for provenance building."""

import os
import shlex
import shutil
from pathlib import Path
from typing import Optional

from snakemake_report_plugin_metadata4ing.jsonld import JsonLdNode, JsonLdNodeMap
from snakemake_report_plugin_metadata4ing.models import CrateFile
from snakemake_report_plugin_metadata4ing.utils import get_mime_type


class FileProvenanceHelpers:
    """Helpers that register provenance file nodes and supplemental files."""

    def _add_shell_supplemental_files(self, job) -> None:
        """Register shell scripts referenced by a job as supplemental files."""
        for shell_cmd in self._job_shell_commands(job):
            script_file, _ = self._extract_script_and_files(shell_cmd)
            if not script_file:
                continue
            resolved_shell_path = self._copy_external_relative_files(script_file)
            self._add_supplemental_file(
                resolved_shell_path,
                resolved_shell_path,
                get_mime_type(resolved_shell_path),
            )

    def _populate_processing_step_files(
        self,
        job,
        node: JsonLdNode,
        file_nodes: JsonLdNodeMap,
        optional_fields: JsonLdNode,
    ) -> None:
        """Attach file references and extracted parameter metadata to a step."""
        for file_path, source in [(f, "input") for f in self._job_input_files(job)] + [
            (f, "output") for f in job.output
        ]:
            if not self._is_file(file_path):
                continue
            file_node = self._add_file(file_path, file_nodes)
            node_key = "has input" if source == "input" else "has output"
            node[node_key].append({"@id": file_node["@id"]})
            self._merge_parameter_metadata(
                optional_fields,
                self._extract_parameters(job.rule, file_path, file_node).get(
                    job.rule, {}
                ),
            )

    def _merge_parameter_metadata(
        self, optional_fields: JsonLdNode, rule_data: JsonLdNode
    ) -> None:
        """Merge extracted parameter references into a method payload."""
        for key in ("has parameter", "investigates"):
            if key in rule_data:
                optional_fields.setdefault(key, []).append(rule_data[key])

    def _add_snakefile_supplemental_file(self) -> None:
        """Register the workflow Snakefile as a supplemental file when found."""
        snakefile = self._find_snakefile()
        if not snakefile:
            return
        snakefile_name, snakepath = snakefile
        self._add_supplemental_file(
            snakefile_name,
            snakepath,
            "text/x-python",
        )

    def _add_file(self, file_path: str, file_dict: JsonLdNodeMap) -> JsonLdNode:
        """Register a file node, copying external files into the workspace."""
        resolved_path = self._copy_external_relative_files(file_path)
        if resolved_path not in file_dict:
            file_dict[resolved_path] = {
                "@id": f"local:file_{len(file_dict)}",
                "@type": "cr:FileObject",
                "label": resolved_path,
            }
        return file_dict[resolved_path]

    def _add_supplemental_file(
        self, source_path: str, dest_path: str, encoding_format: str
    ) -> None:
        """Register a supplemental file for later inclusion in the crate."""
        self.state.supplemental_files[dest_path] = CrateFile(
            source_path=source_path,
            dest_path=dest_path,
            name=source_path,
            encoding_format=encoding_format,
        )

    def _extract_script_and_files(
        self, cmd: str
    ) -> tuple[Optional[str], list[str]]:
        """Parse a shell command and identify likely script and file arguments."""
        interpreters = {
            "python",
            "python3",
            "python2",
            "pypy",
            "pypy3",
            "ruby",
            "perl",
            "node",
            "deno",
            "php",
            "lua",
            "Rscript",
            "R",
            "bash",
            "sh",
            "zsh",
            "ksh",
            "fish",
        }

        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            return None, []

        if not tokens:
            return None, []

        script_path = None
        file_paths = []

        if Path(tokens[0]).name in interpreters:
            start_idx = 1
            for i, tok in enumerate(tokens[1:], start=1):
                if tok.startswith("-"):
                    continue
                script_path = tok
                start_idx = i + 1
                break
        else:
            first = Path(tokens[0])
            if first.suffix and first.suffix not in {".exe", ".bat", ".cmd"}:
                script_path = str(first)
            start_idx = 1

        for tok in tokens[start_idx:]:
            if tok.startswith("-") or tok in {">", "2>&1"} or tok.isnumeric():
                continue
            if Path(tok).suffix or "/" in tok or tok.startswith(".."):
                file_paths.append(tok)

        return script_path, file_paths

    def _find_snakefile(self):
        """Return the local Snakefile name and relative path if it exists."""
        current_dir = os.getcwd()
        for file in os.listdir(current_dir):
            if file.lower() == "snakefile":
                rel_path = os.path.relpath(os.path.join(current_dir, file))
                return file, rel_path
        return None

    def _is_file(self, file_name: str) -> bool:
        """Return whether a path currently exists as a regular file."""
        return os.path.isfile(file_name)

    def _copy_external_relative_files(self, path_str) -> str:
        """Copy external files into the workspace while preserving structure."""
        original_path = Path(path_str).resolve()
        current_dir = Path.cwd().resolve()

        try:
            _ = original_path.relative_to(current_dir)
            return str(path_str)
        except ValueError:
            pass

        common_root = os.path.commonpath([str(current_dir), str(original_path)])
        relative_structure = Path(original_path).relative_to(common_root)
        target_path = Path(self.external_directory_name) / relative_structure

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original_path, target_path)

        return str(target_path)
