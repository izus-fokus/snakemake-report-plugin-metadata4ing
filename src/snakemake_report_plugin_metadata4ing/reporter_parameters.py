import importlib.util
import inspect
import os
from pathlib import Path
from rdflib import Graph
from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)


class ReporterParameters:
    def _extract_parameters_from_benchmark(self, rule, file, file_node):
        """
        Reads a JSON-LD benchmark metadata file, converts it to RDF,
        and extracts parameters for the given configuration.

        Returns the same structure as the old extract_params function.
        """
        if file != "parameters.json":
            return {}

        params = {}
        file_path = self.settings.benchmarkfile
        config_name = self.settings.configname
        rule_name = "run_simulation"

        if rule != rule_name:
            return {}

        file_name = os.path.basename(file_path)

        if not (file_name.endswith(".json") or file_name.endswith(".jsonld")):
            return params

        g = Graph()
        g.parse(file_path, format="json-ld")

        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX m4i: <http://w3id.org/nfdi4ing/metadata4ing#>

        SELECT ?paramLabel ?numVal ?strVal ?unit
        WHERE {{
            ?config rdfs:label ?confLabel .
            FILTER(LCASE(STR(?confLabel)) = LCASE("{config_name}"))

            ?config <http://purl.obolibrary.org/obo/BFO_0000051> ?param .

            ?param rdfs:label ?paramLabel .

            OPTIONAL {{ ?param <http://w3id.org/nfdi4ing/metadata4ing#hasNumericalValue> ?numVal }}
            OPTIONAL {{ ?param <http://w3id.org/nfdi4ing/metadata4ing#hasStringValue> ?strVal }}
            OPTIONAL {{ ?param <http://w3id.org/nfdi4ing/metadata4ing#hasUnit> ?unit }}
        }}
        """

        qres = g.query(query)

        params.setdefault(rule_name, {}).setdefault("has parameter", [])

        for row in qres:
            name = str(row.paramLabel)

            value = None
            if row.numVal is not None:
                value = float(row.numVal)
            elif row.strVal is not None:
                value = str(row.strVal)

            unit = str(row.unit) if row.unit else None

            params[rule_name]["has parameter"].append(
                {
                    name: {
                        "value": value,
                        "unit": unit,
                        "json-path": f"/{name}",
                        "data-type": self.get_type(value),
                    }
                }
            )
        return self._build_metadata_from_params(params, file_node)

    def get_type(self, val):
        if isinstance(val, float):
            return "schema:Float"
        elif isinstance(val, int):
            return "schema:Integer"
        elif isinstance(val, str):
            return "schema:Text"
        return None

    def _build_metadata_from_params(self, params, file_node):
        metadata = {}
        if not params:
            return metadata

        params = self._validate_extract_param_output(params)
        for processing_step_name, processing_step_data in params.items():
            metadata.setdefault(processing_step_name, {})
            for parameter_type in ["has parameter", "investigates"]:
                if parameter_type in processing_step_data:
                    metadata[processing_step_name].setdefault(
                        parameter_type, []
                    )
                    for entry in processing_step_data[parameter_type]:
                        for name, data in entry.items():
                            sanitized_name = name.replace("-", "_")
                            param_id = ""
                            param = {
                                "@type": (
                                    "text variable"
                                    if data["data-type"] == "schema:Text"
                                    else "numerical variable"
                                ),
                                "label": name,
                            }
                            if data["data-type"] == "schema:Text":
                                param["has string value"] = data["value"]
                            else:
                                param["has numerical value"] = data["value"]

                            if data["unit"]:
                                if data["unit"] in self.qudt_mapping_dict:
                                    param["has unit"] = {
                                        "@id": self.qudt_mapping_dict[
                                            data["unit"]
                                        ]
                                    }
                                else:
                                    qudt_unit = self._get_qudt_unit_from_mapping(
                                        data["unit"]
                                    )
                                    self.qudt_mapping_dict[
                                        data["unit"]
                                    ] = qudt_unit
                                    if qudt_unit:
                                        param["has unit"] = {
                                            "@id": qudt_unit
                                        }
                                    else:
                                        self.qudt_mapping_dict[
                                            data["unit"]
                                        ] = data["unit"]
                                        param["has unit"] = {
                                            "@id": data["unit"]
                                        }

                            if param in self.param_dict.values():
                                param_id = next(
                                    (
                                        k
                                        for k, v in self.param_dict.items()
                                        if v == param
                                    ),
                                    None,
                                )
                            else:
                                param_id = f"local:variable_{sanitized_name}_{self.param_counter}"
                                self.param_dict[param_id] = param
                                self.param_counter += 1
                            metadata[processing_step_name][
                                parameter_type
                            ].append({"@id": param_id})
                            self._add_unique_field(
                                sanitized_name, param_id, file_node, data
                            )
        return metadata

    def _extract_parameters_from_paramscript(self, rule, file, file_node):
        extract_params_obj = self._load_param_extractor_obj()
        params = extract_params_obj.extract_params(rule, file)
        return self._build_metadata_from_params(params, file_node)

    def _load_param_extractor_obj(self):
        script_path = Path(self.settings.paramscript).expanduser().resolve()
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        module_path = str(script_path)

        spec = importlib.util.spec_from_file_location(
            "extractor_module", module_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        extractor_class = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ParameterExtractorInterface)
                and obj is not ParameterExtractorInterface
            ):
                extractor_class = obj
                break

        if extractor_class is None:
            raise ImportError(
                "No subclass of ParameterExtractorInterface found in script"
            )

        return extractor_class()

    def _add_unique_field(self, name, param_id, file_node, data):
        unique_key = (
            name,
            param_id,
            file_node.get("@id") if isinstance(file_node, dict) else file_node,
            data.get("data-type"),
        )

        if unique_key in self._unique_fields:
            return

        new_field = {
            "@type": "Field",
            "represents": {"@id": param_id},
            "source": {"@id": f"local:source_{name}_{self.field_counter}"},
            **(
                {"dataType": {"@id": data["data-type"]}}
                if data.get("data-type")
                else {}
            ),
        }

        new_source = {
            "@id": f"local:source_{name}_{self.field_counter}",
            "@type": "cr:DataSource",
            "file object": {"@id": file_node["@id"]},
            "extract": {"@id": f"local:extract_{name}_{self.field_counter}"},
        }

        new_extract = {
            "@id": f"local:extract_{name}_{self.field_counter}",
            "@type": "cr:DataSource",
            "jsonPath": data["json-path"],
        }

        key = f"{name}_{self.field_counter}"
        self.field_dict[key] = {
            "@id": f"local:field_{name}_{self.field_counter}",
            **new_field,
        }
        self.extract_dict[key] = new_extract
        self.source_dict[key] = new_source
        self._unique_fields.add(unique_key)
        self.field_counter += 1

    def _validate_extract_param_output(self, result):
        if not isinstance(result, dict):
            raise TypeError("Function output must be a dictionary.")

        def _validate_entry(entry_key, entry_value):
            """Validate the innermost dictionary with value/unit/json-path/data-type."""
            if not isinstance(entry_key, str):
                raise TypeError(f"Key '{entry_key}' must be a string.")
            if not isinstance(entry_value, dict):
                raise TypeError(
                    f"Value for key '{entry_key}' must be a dictionary."
                )

            required_keys = ["value", "unit", "json-path", "data-type"]
            for rk in required_keys:
                if rk not in entry_value:
                    raise ValueError(
                        f"Missing key '{rk}' in value for '{entry_key}'."
                    )

            if entry_value["unit"] and not isinstance(entry_value["unit"], str):
                raise TypeError(f"'unit' for '{entry_key}' must be a string.")
            if not isinstance(entry_value["json-path"], str):
                raise TypeError(
                    f"'json-path' for '{entry_key}' must be a string."
                )
            if not isinstance(entry_value["data-type"], str):
                raise TypeError(
                    f"'data-type' for '{entry_key}' must be a string."
                )

        def _validate_section(section_name, section_content):
            """Validate a section like 'has parameter' or 'investigates'."""
            if not isinstance(section_content, list):
                raise TypeError(f"'{section_name}' must be a list.")
            for idx, item in enumerate(section_content):
                if not isinstance(item, dict):
                    raise TypeError(
                        f"Each item in '{section_name}' must be a dictionary."
                    )
                if len(item) != 1:
                    raise ValueError(
                        f"Each item in '{section_name}' must have exactly one key, found {len(item)}."
                    )
                inner_key, inner_value = next(iter(item.items()))
                _validate_entry(inner_key, inner_value)

        for root_key, root_value in result.items():
            if not isinstance(root_key, str):
                raise TypeError(f"Root key '{root_key}' must be a string.")
            if not isinstance(root_value, dict):
                raise TypeError(
                    f"Root value for '{root_key}' must be a dictionary."
                )

            if not any(
                k in root_value for k in ["has parameter", "investigates"]
            ):
                raise ValueError(
                    f"Root key '{root_key}' must contain at least 'has parameter' or 'investigates'."
                )

            for section in ["has parameter", "investigates"]:
                if section in root_value:
                    _validate_section(section, root_value[section])

        return result
