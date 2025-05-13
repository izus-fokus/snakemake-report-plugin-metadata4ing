# Metadata4ing reporter for snakemake

This project is based on the Snakemake [reporter plugin](https://github.com/snakemake/snakemake-interface-report-plugins). It provides a custom reporter plugin for [Metadat4ing ontology](https://nfdi4ing.pages.rwth-aachen.de/metadata4ing/metadata4ing/1.2.1/index.html) , which can be used to extract and report metadata from Snakemake pipelines.

## Installation

Install the plugin using pip (currently not working):
```
pip install snakemake_report_plugin_metadat4ing
```
or from the source code:
```
poetry build
pip install --force-reinstall dist/snakemake_report_plugin_metadat4ing-0.1.0-py3-none-any.whl
```
Then, use it as the reporter in your Snakemake workflow:
```
snakemake --reporter metadat4ing ...
```

## Parameter Extractor
It is possible to pass a script as a parameter extractor. You can write your own extractor in a separate Python script and pass it to the reporter using the `paramscript` argument:

```
snakemake --reporter metadat4ing --report-metadat4ing-paramscript /Path_to_Extractor/my_extractor.py ...
```

Please note that, your extractor should implement the `ParameterExtractorInterface`.
```
class ParameterExtractorInterface(ABC):
    @abstractmethod
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        ...
```

The `extract_params` method should return a dictionary where:

- **Keys** are the names of the parameters.
- **Values** are dictionaries with the following keys:
  - `value`: the parameter value
  - `unit`: the unit of the value (if applicable)
  - `json-path`: the path to this value in the output JSON
  - `data-type`: the data type of the value

A sample extractor is provided in `sample_extractor/my_extractor.py`.
