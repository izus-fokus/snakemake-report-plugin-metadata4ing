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
### `paramscript`
It is possible to pass a script as a parameter extractor. You can write your own extractor in a separate Python script and pass it to the reporter using the `paramscript` argument:

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
  - `value`: parameter value
  - `unit`: unit of the value (if applicable). It will be mapped to the neartest [QUDT](https://www.qudt.org/doc/DOC_VOCAB-UNITS.html) unit.
  - `json-path`: the path to this value in the output JSON
  - `data-type`: the data type of the value

A sample extractor is provided [here](sample_extractor/my_extractor.py)``.

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

Please note that if you provide another name (or even multiple entries as the output), it adds new nodes (as processing steps) to the give rule. These new nodes would be add as a `m4i:part of` to the original processing step. This would be hepful if you have a single file as the summary where it summarizes all the simulation results (input and output parameters).

For example, if the meothd is called with a rule_name like `run_simulation` and the returned dictionary is like:

```json
{
    "run_simulation_1": {
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
    },
    "run_simulation_2": {
        "has parameter": {
            "length": {
                "value": 10,
                "unit": "m",
                "json-path": "/parameters.json/inputs",
                "data-type": "float"
            }
        },
        "investigates": {
            "stress": {
                "value": 2.0,
                "unit": "MPa",
                "json-path": "summary.json",
                "data-type": "float"
            }
        }
    }
}
```
```json
{
    "first_run": {
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
    },
    "second_run": {
        "has parameter": {
            "length": {
                "value": 10,
                "unit": "m",
                "json-path": "/parameters.json/inputs",
                "data-type": "float"
            }
        },
        "investigates": {
            "stress": {
                "value": 2.0,
                "unit": "MPa",
                "json-path": "summary.json",
                "data-type": "float"
            }
        }
    }
}
```

Then in the final graph we have:
```ttl

local:processing_step_* a schema:Action ;
    rdfs:label "run_simualtion" ;
    .....

local:processing_step_** a schema:Action ;
    rdfs:label "first_run" ;
    schema:isPartOf local:processing_step_* ;
    .....

local:processing_step_*** a schema:Action ;
    rdfs:label "second_run" ;
    schema:isPartOf local:processing_step_* ;   
    .....
    
```

### `filename`
The name of the final ZIP file. If not provided, it defaults to `ro-crate-metadata-{simulation_hash}.zip`, where `simulation_hash` is a 16-character hash computed from the content of the graph.

```
snakemake --reporter metadata4ing --report-metadata4ing-filename MyFile ...
```


