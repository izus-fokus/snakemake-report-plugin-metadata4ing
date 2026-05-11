"""Small utility helpers shared across the package.

The functions in this module are intentionally small and side-effect free so
they can be reused in both provenance extraction and crate-building code.
"""

import mimetypes
import os
import re
from pathlib import Path


def get_mime_type(file_name: str) -> str:
    """Guess the MIME type for a file name and fall back safely.

    Args:
        file_name: File path or file name whose MIME type should be guessed.

    Returns:
        The guessed MIME type. Falls back to ``application/octet-stream`` when
        the standard library cannot infer a more specific value.
    """
    file_name = Path(file_name).name
    mime_type, _ = mimetypes.guess_type(file_name, strict=False)
    return mime_type or "application/octet-stream"


def validate_filename(filename: str) -> None:
    """Validate an output filename against common invalid path patterns.

    Args:
        filename: Proposed output filename or filename stem.

    Returns:
        None. Successful validation is indicated by the absence of an
        exception.

    Raises:
        ValueError: If the value is empty, contains disallowed characters,
            matches a Windows reserved device name, or points to an existing
            directory.
    """
    if not filename or filename.strip() == "":
        raise ValueError("Filename cannot be empty.")

    illegal_pattern = r'[<>:"/\\|?*]'
    if re.search(illegal_pattern, filename):
        raise ValueError(f"Filename '{filename}' contains illegal characters.")

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
