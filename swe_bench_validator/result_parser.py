"""
Result parsing and validation for SWE-bench evaluation outputs.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ValidationResult:
    """
    Represents the result of validating a single SWE-bench data point.

    Attributes:
        instance_id: Unique identifier for the instance
        success: Overall validation success (all tests passed)
        fail_to_pass_results: Dict mapping test names to pass/fail status
        pass_to_pass_results: Dict mapping test names to pass/fail status
        errors: List of error messages encountered during validation
        execution_time: Total time taken for evaluation in seconds
        docker_logs: Optional path to Docker execution logs
        patch_applied: Whether the patch was successfully applied
    """

    instance_id: str
    success: bool
    fail_to_pass_results: Dict[str, bool] = field(default_factory=dict)
    pass_to_pass_results: Dict[str, bool] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    docker_logs: Optional[str] = None
    patch_applied: bool = False

    def to_dict(self) -> dict:
        """
        Serialize validation result to dictionary format.

        Returns:
            Dictionary representation of the validation result
        """
        return {
            "instance_id": self.instance_id,
            "success": self.success,
            "patch_applied": self.patch_applied,
            "fail_to_pass": self.fail_to_pass_results,
            "pass_to_pass": self.pass_to_pass_results,
            "errors": self.errors,
            "execution_time": self.execution_time,
            "docker_logs": self.docker_logs,
        }

    def to_json(self) -> str:
        """
        Serialize validation result to JSON string.

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=2)

    def get_summary(self) -> str:
        """
        Generate a human-readable summary of the validation result.

        Returns:
            Formatted summary string
        """
        lines = []

        # Header
        status_icon = "✓" if self.success else "✗"
        status_text = "SUCCESS" if self.success else "FAILED"
        lines.append(f"\n{status_icon} Validation {status_text} for {self.instance_id}")
        lines.append("=" * 70)

        # Patch status
        patch_icon = "✓" if self.patch_applied else "✗"
        lines.append(
            f"\nPatch Application: {patch_icon} {'Success' if self.patch_applied else 'Failed'}"
        )

        # FAIL_TO_PASS results
        if self.fail_to_pass_results:
            lines.append(f"\nFAIL_TO_PASS Tests ({len(self.fail_to_pass_results)}):")
            for test_name, passed in self.fail_to_pass_results.items():
                icon = "✓" if passed else "✗"
                status = "PASSED" if passed else "FAILED"
                lines.append(f"  {icon} {status}: {test_name}")

        # PASS_TO_PASS results
        if self.pass_to_pass_results:
            passed_count = sum(1 for p in self.pass_to_pass_results.values() if p)
            total_count = len(self.pass_to_pass_results)
            lines.append(f"\nPASS_TO_PASS Tests ({passed_count}/{total_count} passed):")

            # Show failed tests or summary
            failed_tests = [
                name for name, passed in self.pass_to_pass_results.items() if not passed
            ]
            if failed_tests:
                for test_name in failed_tests:
                    lines.append(f"  ✗ FAILED (regression): {test_name}")
            else:
                lines.append(f"  ✓ All {total_count} tests passed")

        # Errors
        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  • {error}")

        # Execution time
        lines.append(f"\nExecution Time: {self.execution_time:.2f} seconds")

        # Docker logs location
        if self.docker_logs:
            lines.append(f"Docker Logs: {self.docker_logs}")

        lines.append("=" * 70)
        return "\n".join(lines)

    @property
    def fail_to_pass_count(self) -> int:
        """Number of FAIL_TO_PASS tests that passed."""
        return sum(1 for p in self.fail_to_pass_results.values() if p)

    @property
    def pass_to_pass_count(self) -> int:
        """Number of PASS_TO_PASS tests that passed."""
        return sum(1 for p in self.pass_to_pass_results.values() if p)

    @property
    def total_tests(self) -> int:
        """Total number of tests."""
        return len(self.fail_to_pass_results) + len(self.pass_to_pass_results)

    @property
    def passed_tests(self) -> int:
        """Total number of tests that passed."""
        return self.fail_to_pass_count + self.pass_to_pass_count


def parse_evaluation_results(
    report: dict, instance_id: str, execution_time: float = 0.0
) -> ValidationResult:
    """
    Parse SWE-bench evaluation report into ValidationResult.

    The report format from SWE-bench harness:
    {
        "patch_is_None": bool,
        "patch_exists": bool,
        "patch_successfully_applied": bool,
        "resolved": bool,
        "tests_status": {
            "FAIL_TO_PASS": {
                "success": [test_names...],
                "failure": [test_names...]
            },
            "PASS_TO_PASS": {
                "success": [test_names...],
                "failure": [test_names...]
            }
        }
    }

    Args:
        report: SWE-bench evaluation report dictionary
        instance_id: Instance identifier
        execution_time: Total execution time

    Returns:
        ValidationResult object
    """
    errors = []
    fail_to_pass_results = {}
    pass_to_pass_results = {}

    # Check if patch was applied (SWE-bench uses 'patch_successfully_applied')
    patch_applied = report.get("patch_successfully_applied", False)
    if not patch_applied:
        errors.append("Failed to apply patch to repository")

    # Extract test results from tests_status
    tests_status = report.get("tests_status", {})

    # Extract FAIL_TO_PASS results
    if "FAIL_TO_PASS" in tests_status:
        f2p = tests_status["FAIL_TO_PASS"]
        # Map test names to pass/fail status
        for test_name in f2p.get("success", []):
            fail_to_pass_results[test_name] = True
        for test_name in f2p.get("failure", []):
            fail_to_pass_results[test_name] = False

    # Extract PASS_TO_PASS results
    if "PASS_TO_PASS" in tests_status:
        p2p = tests_status["PASS_TO_PASS"]
        # Map test names to pass/fail status
        for test_name in p2p.get("success", []):
            pass_to_pass_results[test_name] = True
        for test_name in p2p.get("failure", []):
            pass_to_pass_results[test_name] = False

    # Check for test failures
    all_passed = (
        patch_applied
        and (all(fail_to_pass_results.values()) if fail_to_pass_results else True)
        and (all(pass_to_pass_results.values()) if pass_to_pass_results else True)
    )

    # Add specific error messages
    if fail_to_pass_results:
        failed_fail_to_pass = [
            name for name, passed in fail_to_pass_results.items() if not passed
        ]
        for test_name in failed_fail_to_pass:
            errors.append(f"FAIL_TO_PASS test did not pass: {test_name}")

    if pass_to_pass_results:
        failed_pass_to_pass = [
            name for name, passed in pass_to_pass_results.items() if not passed
        ]
        for test_name in failed_pass_to_pass:
            errors.append(f"PASS_TO_PASS test failed (regression): {test_name}")

    return ValidationResult(
        instance_id=instance_id,
        success=all_passed and len(errors) == 0,
        fail_to_pass_results=fail_to_pass_results,
        pass_to_pass_results=pass_to_pass_results,
        errors=errors,
        execution_time=execution_time,
        patch_applied=patch_applied,
    )


def format_error_message(result: ValidationResult) -> str:
    """
    Format a detailed error message for a failed validation.

    Args:
        result: ValidationResult object

    Returns:
        Formatted error message string
    """
    if result.success:
        return f"✓ Validation passed for {result.instance_id}"

    lines = [f"\n✗ Validation FAILED for {result.instance_id}\n"]

    if not result.patch_applied:
        lines.append("ERROR: Failed to apply patch to repository")
        lines.append("  The patch could not be applied cleanly to the codebase.")
        lines.append("  This could indicate:")
        lines.append("    - Incorrect base_commit in the data point")
        lines.append("    - Malformed patch format")
        lines.append("    - Conflicting changes in the repository\n")

    failed_fail_to_pass = [
        name for name, passed in result.fail_to_pass_results.items() if not passed
    ]
    if failed_fail_to_pass:
        lines.append(
            f"FAIL_TO_PASS tests that did not pass ({len(failed_fail_to_pass)}):"
        )
        for test_name in failed_fail_to_pass:
            lines.append(f"  ✗ {test_name}")
        lines.append("")

    failed_pass_to_pass = [
        name for name, passed in result.pass_to_pass_results.items() if not passed
    ]
    if failed_pass_to_pass:
        lines.append(
            f"PASS_TO_PASS tests that failed (regressions) ({len(failed_pass_to_pass)}):"
        )
        for test_name in failed_pass_to_pass:
            lines.append(f"  ✗ {test_name}")
        lines.append("")

    if result.errors:
        lines.append("Additional errors:")
        for error in result.errors:
            lines.append(f"  • {error}")

    return "\n".join(lines)
