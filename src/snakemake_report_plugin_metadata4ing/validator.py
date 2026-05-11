from __future__ import annotations

from pathlib import Path

from rocrate_validator import models, services


class ROCrateValidationError(ValueError):
    pass


def validate_rocrate(
    rocrate_uri: str | Path,
    profile_identifier: str = "ro-crate-1.1",
) -> None:
    """
    Validates the RO-Crate against the specified profile.

    Uses the rocrate-validator library to check if the RO-Crate metadata
    conforms to the specified profile with required severity level.
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
