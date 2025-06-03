from abc import ABC, abstractmethod

class ParameterExtractorInterface(ABC):
    @abstractmethod
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        ...
    
    @abstractmethod
    def extract_tools(self, rule_name: str, env_file_content: str) -> dict:
        ...    