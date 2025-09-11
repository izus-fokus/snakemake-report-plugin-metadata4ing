from abc import ABC, abstractmethod

class ParameterExtractorInterface(ABC):
    @abstractmethod
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        ...