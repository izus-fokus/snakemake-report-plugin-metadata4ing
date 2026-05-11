"""Validation helpers for generated RO-Crates.

This module centralizes interaction with ``rocrate_validator`` so the rest of
the package can treat validation as a single, well-defined step.
"""

from __future__ import annotations

from pathlib import Path

from rocrate_validator import models, services


class ROCrateValidationError(ValueError):
    """Raised when a generated RO-Crate fails profile validation.

    The message contains one line per validator issue, including the severity,
    originating check identifier, and validator message.
    """

    pass


def validate_rocrate(
    rocrate_uri: str | Path,
    profile_identifier: str = "ro-crate-1.1",
) -> None:
    """Validate a crate path against a selected RO-Crate profile.

    Args:
        rocrate_uri: Path to the generated RO-Crate ZIP file or extracted
            directory to validate.
        profile_identifier: Profile token understood by ``rocrate_validator``,
            such as ``ro-crate-1.1`` or ``provenance-run-crate-0.5``.

    Returns:
        None. Successful validation is indicated by the absence of an
        exception.

    Raises:
        ROCrateValidationError: If the validator reports any issue at required
            severity.
    """
    settings = services.ValidationSettings(
        rocrate_uri=Path(rocrate_uri),
        profile_identifier=profile_identifier,
        requirement_severity=models.Severity.REQUIRED,
    )

    result = services.validate(settings)

    if result.has_issues():
        raise ROCrateValidationError(
            "RO-Crate is invalid!\n"
            + "\n".join(
                f"Detected issue of severity {issue.severity.name} with check "
                f'"{issue.check.identifier}": {issue.message}'
                for issue in result.get_issues()
            )
        )
