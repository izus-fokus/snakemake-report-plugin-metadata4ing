"""Parameter, field, source, and extract node helpers."""

from snakemake_report_plugin_metadata4ing.jsonld import JsonLdNode, JsonLdNodeMap


class ParameterProvenanceHelpers:
    """Helpers that convert extractor output into provenance graph nodes."""

    def _extract_parameters(
        self, rule: str, file_path: str, file_node: JsonLdNode
    ) -> JsonLdNodeMap:
        """Extract parameter metadata for a file and convert it to node refs."""
        metadata: JsonLdNodeMap = {}
        params = self.parameter_extractor.extract(rule, file_path)
        for processing_step_name, processing_step_data in params.items():
            metadata.setdefault(processing_step_name, {})
            for parameter_type in ["has parameter", "investigates"]:
                if parameter_type not in processing_step_data:
                    continue
                metadata[processing_step_name].setdefault(parameter_type, [])
                for entry in processing_step_data[parameter_type]:
                    for name, data in entry.items():
                        sanitized_name = name.replace("-", "_")
                        param_node = self._build_parameter_node(name, data)
                        param_id = self._intern_parameter_node(
                            sanitized_name, param_node
                        )
                        metadata[processing_step_name][parameter_type].append(
                            {"@id": param_id}
                        )
                        self._add_unique_field(
                            sanitized_name, param_id, file_node, data
                        )
        return metadata

    def _build_parameter_node(self, name: str, data: JsonLdNode) -> JsonLdNode:
        """Build a variable node from extractor output metadata."""
        param_node: JsonLdNode = {
            "@type": (
                "text variable"
                if data["data-type"] == "schema:Text"
                else "numerical variable"
            ),
            "label": name,
        }
        if data["data-type"] == "schema:Text":
            param_node["has string value"] = data["value"]
        else:
            param_node["has numerical value"] = data["value"]
        unit_ref = self._resolve_unit_reference(data.get("unit"))
        if unit_ref:
            param_node["has unit"] = {"@id": unit_ref}
        return param_node

    def _resolve_unit_reference(self, unit: str | None) -> str | None:
        """Resolve and cache the identifier used for a parameter unit."""
        if not unit:
            return None
        if unit not in self.state.qudt_mapping:
            resolved_unit = self.resources.get_qudt_unit(unit)
            self.state.qudt_mapping[unit] = resolved_unit or unit
        return self.state.qudt_mapping[unit]

    def _intern_parameter_node(
        self, sanitized_name: str, param_node: JsonLdNode
    ) -> str:
        """Deduplicate a parameter node and return its stable local identifier."""
        for key, value in self.state.parameters.items():
            if value == param_node:
                return key
        param_id = f"local:variable_{sanitized_name}_{self.state.param_counter}"
        self.state.parameters[param_id] = param_node
        self.state.param_counter += 1
        return param_id

    def _add_unique_field(self, name, param_id, file_node, data):
        """Create a field/source/extract triple if it has not been seen before."""
        unique_key = (
            name,
            param_id,
            file_node.get("@id") if isinstance(file_node, dict) else file_node,
            data.get("data-type"),
        )

        if unique_key in self.state.unique_fields:
            return

        new_field = {
            "@type": "Field",
            "represents": {"@id": param_id},
            "source": {"@id": f"local:source_{name}_{self.state.field_counter}"},
            **(
                {"dataType": {"@id": data["data-type"]}}
                if data.get("data-type")
                else {}
            ),
        }

        new_source = {
            "@id": f"local:source_{name}_{self.state.field_counter}",
            "@type": "cr:DataSource",
            "file object": {"@id": file_node["@id"]},
            "extract": {
                "@id": f"local:extract_{name}_{self.state.field_counter}"
            },
        }

        new_extract = {
            "@id": f"local:extract_{name}_{self.state.field_counter}",
            "@type": "cr:DataSource",
            "jsonPath": data["json-path"],
        }

        key = f"{name}_{self.state.field_counter}"
        self.state.fields[key] = {
            "@id": f"local:field_{name}_{self.state.field_counter}",
            **new_field,
        }
        self.state.extracts[key] = new_extract
        self.state.sources[key] = new_source
        self.state.unique_fields.add(unique_key)
        self.state.field_counter += 1
