import hashlib
import json
import mimetypes
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from importlib import resources
from rdflib import Graph


class ReporterIO:
    def _read_config(self):
        if not self.settings.config:
            return None

        config_path = Path(self.settings.config).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            try:
                self.config_data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Error parsing JSON config file: {e}") from e

    def _extend_rocrate_context(self):
        metadata4ing_context = self.context_data.get("@context", {})
        metadata4ing_context.pop("@vocab", None)
        metadata4ing_context.pop("description", None)
        metadata4ing_context["softwareVersion"] = {"@id": "schema:softwareVersion"}
        metadata4ing_context["dataType"] = {"@id": "cr:dataType"}
        metadata4ing_context["extract"] = {"@id": "cr:extract"}
        metadata4ing_context["jsonPath"] = {"@id": "cr:jsonPath"}
        metadata4ing_context["schema"] = "http://schema.org/"
        self.crate.metadata.extra_contexts.append(metadata4ing_context)

    def _add_rocrate_config_data(self):
        rocrate_info = self.config_data.get("rocrate", {})
        self.crate.name = rocrate_info.get("name")
        self.crate.description = rocrate_info.get("description")
        self.crate.license = rocrate_info.get("license")

    def _get_context(self):
        with resources.files(
            "snakemake_report_plugin_metadata4ing.ontologies"
        ).joinpath("metadata4ing.jsonld").open("r", encoding="utf-8") as f:
            self.context_data = json.load(f)

    def _get_qudt(self):
        with resources.files(
            "snakemake_report_plugin_metadata4ing.ontologies"
        ).joinpath("qudt.ttl").open("r", encoding="utf-8") as f:
            qudt_data = f.read()
            self.unit_graph.parse(data=qudt_data, format="ttl")

    def _get_qudt_unit_from_mapping(self, unit: str) -> str | None:
        with resources.files(
            "snakemake_report_plugin_metadata4ing.ontologies"
        ).joinpath("qudt-mapping.json").open("r", encoding="utf-8") as f:
            mapping = json.load(f)
        pint_unit = self.ureg.parse_units(unit)
        if str(pint_unit) in mapping:
            return f"unit:{mapping[str(pint_unit)]}"
        return unit

    def _add_ro_crate_file_nodes(self, file_nodes):
        _ = self.crate.add_file(
            self.provenance_filename,
            dest_path=self.provenance_filename,
            properties={
                "name": self.provenance_filename,
                "encodingFormat": "application/ld+json",
                "conformsTo": [
                    "https://w3id.org/ro/crate/1.1",
                    "https://w3id.org/nfdi4ing/metadata4ing/1.3.1",
                ],
            },
        )

        _ = self.crate.add_file(
            self.provenance_ttl_filename,
            dest_path=self.provenance_ttl_filename,
            properties={
                "name": self.provenance_ttl_filename,
                "encodingFormat": "text/turtle",
            },
        )

        for file in file_nodes.keys():
            _ = self.crate.add_file(
                file,
                dest_path=file,
                properties={
                    "name": file,
                    "encodingFormat": self._get_mime_type(file),
                },
            )

    def _create_ttl_from_jsonld(self, data: dict):
        Graph().parse(data=data, format="json-ld").serialize(
            "provenance.ttl", format="ttl"
        )

    def _create_ro_crate_file(self):
        if self.settings.filename:
            self.crate.write_zip(f"{self.settings.filename}.zip")
        else:
            self.crate.write_zip(
                f"ro-crate-metadata-{self.simulation_hash}.zip"
            )

    def _get_mime_type(self, file_name: str) -> str:
        file_name = Path(file_name).name
        mime_type, _ = mimetypes.guess_type(file_name, strict=False)
        return mime_type or "application/octet-stream"

    def _extract_script_and_files(
        self, cmd: str
    ) -> tuple[Optional[str], list[str]]:
        _INTERPRETERS = {
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

        if Path(tokens[0]).name in _INTERPRETERS:
            for i, tok in enumerate(tokens[1:], start=1):
                if tok.startswith("-"):
                    continue
                script_path = tok
                break
            start_idx = i + 1 if script_path else 1
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
        current_dir = os.getcwd()
        for file in os.listdir(current_dir):
            if file.lower() == "snakefile":
                rel_path = os.path.relpath(os.path.join(current_dir, file))
                return (file, rel_path)
        return None

    def _is_file(self, file_name: str) -> bool:
        return os.path.isfile(file_name)

    def _random_hash_from_json(self, json_content: dict, length=8) -> str:
        json_str = json.dumps(json_content, sort_keys=True).encode("utf-8")
        hash_value = hashlib.sha256(json_str).hexdigest()
        return hash_value[:length]

    def _copy_external_relative_files(self, path_str) -> str:
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

    def _create_external_directory(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    def _get_time_str(self, timestamp) -> str:
        try:
            return f"{datetime.fromtimestamp(timestamp)}"
        except Exception:
            return ""

    def _clean_data(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        os.remove(self.provenance_filename)
        os.remove(self.provenance_ttl_filename)

    def _replace_terms(self, obj, mapping: dict):
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                new_key = mapping.get(k, k)
                new_obj[new_key] = self._replace_terms(v, mapping)
            return new_obj

        elif isinstance(obj, list):
            return [self._replace_terms(v, mapping) for v in obj]

        elif isinstance(obj, str):
            obj = obj.replace("local:", "#")
            return mapping.get(obj, obj)

        else:
            return obj

    def _add_provenance_nodes_to_crate(self, jsonld) -> None:
        nodes = jsonld["@graph"]
        for node in nodes:
            entity_id = node["@id"]
            if entity_id is None or self.crate.get(entity_id):
                continue
            self.crate.add_jsonld(node)

    def _validate_filename(self, filename: str) -> None:
        if not filename or filename.strip() == "":
            raise ValueError("Filename cannot be empty.")

        illegal_pattern = r'[<>:"/\\|?*]'
        if re.search(illegal_pattern, filename):
            raise ValueError(
                f"Filename '{filename}' contains illegal characters."
            )

        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *{f"COM{i}" for i in range(1, 10)},
            *{f"LPT{i}" for i in range(1, 10)},
        }

        if filename.upper().split(".")[0] in reserved_names:
            raise ValueError(f"Filename '{filename}' is reserved on Windows.")

        if os.path.isdir(filename):
            raise ValueError(f"'{filename}' is a directory, not a file.")

        return None
