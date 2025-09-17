# Metadata4ing reporter for snakemake

This project is based on the Snakemake [reporter plugin](https://github.com/snakemake/snakemake-interface-report-plugins). It provides a custom reporter plugin for [metadata4ing ontology](https://nfdi4ing.pages.rwth-aachen.de/metadata4ing/metadata4ing/1.2.1/index.html) , which can be used to extract and report metadata from Snakemake pipelines.

## Installation

Install the plugin using pip:
```
python -m pip install git+https://github.com/izus-fokus/snakemake-report-plugin-metadata4ing
```
or from the source code:
```
poetry build
pip install --force-reinstall dist/snakemake_report_plugin_metadata4ing-1.0.0-py3-none-any.whl
```
Then, use it as the reporter in your Snakemake workflow:
```
snakemake --reporter metadata4ing ...
```
## Output Format

The reporter creates a zip file, which contains a RO-Crate zip file which contains important files from the simulation like the input and output files for each rule. It also creates 3 files
-- `provenance.jsonld`: Knowledge graph based on [Metadata4ing ontology](https://nfdi4ing.pages.rwth-aachen.de/metadata4ing/metadata4ing/1.2.1/index.html)
-- `provenance.ttl`: Same as `provenance.jsonld` graph but in [turtle](https://www.w3.org/TR/turtle/) format.
-- `ro-crate-metadata.json`: [Research Object Crate](https://www.researchobject.org/ro-crate/) file describing the dataset. 

## Reporter Parameters
- **paramscript** It is possible to pass a script as a parameter extractor. You can write your own extractor in a separate Python script and pass it to the reporter using the `paramscript` argument:

```
snakemake --reporter metadata4ing --report-metadata4ing-paramscript /Path_to_Extractor/my_extractor.py ...
```

Please note that, your extractor should implement the [`ParameterExtractorInterface`](src/snakemake_report_plugin_metadata4ing/interfaces.py).
```
class ParameterExtractorInterface(ABC):
    @abstractmethod
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        ...
```

The `extract_params` method should return a dictionary where:

- **Keys** are the name of the corresponding procssing step (or the `rule_name`).
- **Values** another dictionary with two keys, `has parameter` and  `investigates`. These two keys resembele the input and output of that processing step, respectively. Each of these entries again should be a dictionary where the varaiable name is key and values as another dictionary with fixed key names:
- **Values** are dictionaries with the following keys:
  - `value`: the parameter value
  - `unit`: the unit of the value (if applicable)
  - `json-path`: the path to this value in the output JSON
  - `data-type`: the data type of the value

For example, a simple dictionary could liek this:
```json
{
    "run_simulation": {
        "has parameter": {
            "length": {
                "value": 15,
                "unit": "m",
                "json-path": "/parameters.json/inputs",
                "data-type": "float"
            }
        },
        "investigates": {
            "stress": {
                "value": 1.0,
                "unit": "MPa",
                "json-path": "summary.json",
                "data-type": "float"
            }
        }
    }
}
```

A sample extractor is provided in `sample_extractor/my_extractor.py`.
