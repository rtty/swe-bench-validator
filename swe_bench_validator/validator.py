"""
Core validation logic for SWE-bench data points.
"""

import json
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

import docker
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from swebench.harness.constants import (
    KEY_INSTANCE_ID,
    KEY_MODEL,
    KEY_PREDICTION,
    RUN_EVALUATION_LOG_DIR,
)

from .result_parser import ValidationResult, parse_evaluation_results


console = Console()


class ValidationError(Exception):
    """Exception raised when validation fails."""

    pass


class SWEBenchValidator:
    """
    Validates SWE-bench data points using the official evaluation harness.

    This validator:
    1. Loads data points from JSON files
    2. Converts them to prediction format using the golden patch
    3. Runs SWE-bench evaluation in Docker containers
    4. Validates that FAIL_TO_PASS and PASS_TO_PASS tests pass
    """

    def __init__(
        self,
        data_points_dir: Path = Path("data_points"),
        timeout_per_instance: int = 900,  # 15 minutes default
        force_rebuild: bool = False,
        cache_level: str = "env",
        verbose: bool = False,
    ):
        """
        Initialize the validator.

        Args:
            data_points_dir: Directory containing data point JSON files
            timeout_per_instance: Timeout for each instance evaluation in seconds
            force_rebuild: Whether to force rebuild Docker images
            cache_level: Docker cache level (none/base/env/instance)
            verbose: Enable verbose logging
        """
        self.data_points_dir = Path(data_points_dir)
        self.timeout = timeout_per_instance
        self.force_rebuild = force_rebuild
        self.cache_level = cache_level
        self.verbose = verbose

        if not self.data_points_dir.exists():
            raise ValueError(
                f"Data points directory does not exist: {self.data_points_dir}"
            )

    def check_docker_available(self) -> tuple[bool, Optional[str]]:
        """
        Check if Docker is available and running.

        Returns:
            Tuple of (is_available, error_message)
        """
        try:
            client = docker.from_env()
            client.ping()
            info = client.info()

            if self.verbose:
                console.print(f"[green]✓[/green] Docker is running")
                console.print(f"  Version: {info.get('ServerVersion', 'unknown')}")
                console.print(f"  OS: {info.get('OperatingSystem', 'unknown')}")

            return True, None
        except docker.errors.DockerException as e:
            error_msg = f"Docker is not available: {str(e)}"
            return False, error_msg
        except Exception as e:
            error_msg = f"Failed to connect to Docker: {str(e)}"
            return False, error_msg

    def load_data_point(self, file_path: Path) -> dict:
        """
        Load and validate a data point from a JSON file.

        Args:
            file_path: Path to the JSON file

        Returns:
            Data point dictionary

        Raises:
            ValidationError: If the file is invalid or missing required fields
        """
        if not file_path.exists():
            raise ValidationError(f"Data point file does not exist: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data_point = json.load(f)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON in {file_path}: {str(e)}")

        # Validate required fields for SWEbenchInstance
        required_fields = [
            "instance_id",
            "repo",
            "base_commit",
            "patch",
            "test_patch",
            "problem_statement",
            "hints_text",
            "created_at",
            "version",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "environment_setup_commit",
        ]

        missing_fields = [field for field in required_fields if field not in data_point]
        if missing_fields:
            raise ValidationError(
                f"Missing required fields in {file_path}: {', '.join(missing_fields)}"
            )

        # Validate patch is not empty
        if not data_point["patch"] or not data_point["patch"].strip():
            raise ValidationError(f"Empty patch in {file_path}")

        # Validate test lists format (but keep as strings for SWEbenchInstance)
        for field in ["FAIL_TO_PASS", "PASS_TO_PASS"]:
            # Ensure they are JSON strings
            if isinstance(data_point[field], list):
                # Convert list to JSON string for SWEbenchInstance compatibility
                data_point[field] = json.dumps(data_point[field])
            elif isinstance(data_point[field], str):
                # Validate it's valid JSON
                try:
                    json.loads(data_point[field])
                except json.JSONDecodeError:
                    raise ValidationError(
                        f"Invalid JSON format for {field} in {file_path}"
                    )
            else:
                raise ValidationError(
                    f"{field} must be a string or list in {file_path}"
                )

        return data_point

    def convert_to_prediction(self, data_point: dict) -> dict:
        """
        Convert a data point to SWE-bench prediction format.

        Uses the golden patch from the data point as the model prediction.

        Args:
            data_point: Data point dictionary

        Returns:
            Prediction dictionary in SWE-bench format
        """
        return {
            KEY_INSTANCE_ID: data_point["instance_id"],
            KEY_MODEL: "golden",
            KEY_PREDICTION: data_point["patch"],
        }

    def validate_single(self, data_point_path: Path) -> ValidationResult:
        """
        Validate a single data point.

        Args:
            data_point_path: Path to the data point JSON file

        Returns:
            ValidationResult object
        """
        instance_id = data_point_path.stem
        start_time = time.time()

        try:
            if self.verbose:
                console.print(f"\n[bold]Validating {instance_id}...[/bold]")

            # Load data point
            data_point = self.load_data_point(data_point_path)
            instance_id = data_point["instance_id"]

            if self.verbose:
                console.print(f"  Repository: {data_point['repo']}")
                console.print(f"  Base commit: {data_point['base_commit'][:8]}...")
                # Parse test counts (they are JSON strings)
                fail_to_pass = json.loads(data_point["FAIL_TO_PASS"])
                pass_to_pass = json.loads(data_point["PASS_TO_PASS"])
                console.print(f"  FAIL_TO_PASS tests: {len(fail_to_pass)}")
                console.print(f"  PASS_TO_PASS tests: {len(pass_to_pass)}")

            # Convert to prediction format
            prediction = self.convert_to_prediction(data_point)

            # Create temporary predictions file
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as f:
                predictions_path = Path(f.name)
                f.write(json.dumps(prediction) + "\n")

            # Create temporary dataset file with single instance
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as f:
                dataset_path = Path(f.name)
                f.write(json.dumps(data_point) + "\n")

            try:
                # Run evaluation using SWE-bench harness
                if self.verbose:
                    console.print(f"\n[yellow]Running evaluation in Docker...[/yellow]")

                import io
                import sys

                # Capture output if not verbose
                old_stdout = None
                old_stderr = None
                if not self.verbose:
                    old_stdout = sys.stdout
                    old_stderr = sys.stderr
                    sys.stdout = io.StringIO()
                    sys.stderr = io.StringIO()

                try:
                    # Import required SWE-bench functions
                    import docker
                    from swebench.harness.constants import SWEbenchInstance
                    from swebench.harness.run_evaluation import (
                        build_env_images,
                        make_test_spec,
                        run_instance,
                    )

                    # Cast data point to SWEbenchInstance and create test spec
                    test_spec = make_test_spec(data_point)  # type: ignore

                    # Set up Docker client
                    client = docker.from_env()

                    if self.verbose:
                        console.print("[cyan]Building Docker images...[/cyan]")

                    # Build environment images if they don't exist
                    # This will build base and environment layers if needed
                    build_env_images(
                        client=client,
                        dataset=[test_spec],
                        force_rebuild=self.force_rebuild,
                        max_workers=1,
                    )

                    if self.verbose:
                        console.print(
                            "[cyan]Docker images ready, running instance...[/cyan]"
                        )

                    # Set up run configuration
                    run_id = f"validation_{instance_id}"
                    rm_image = False  # Keep images for caching

                    # Run the instance
                    result_tuple = run_instance(
                        test_spec=test_spec,
                        pred=prediction,
                        rm_image=rm_image,
                        force_rebuild=self.force_rebuild,
                        client=client,
                        run_id=run_id,
                        timeout=self.timeout,
                    )
                finally:
                    if not self.verbose:
                        sys.stdout = old_stdout
                        sys.stderr = old_stderr

                # Check if evaluation succeeded
                if result_tuple is None:
                    raise ValidationError("Evaluation failed - check logs for details")

                _, report = result_tuple

                # Parse results
                execution_time = time.time() - start_time

                # The report is nested: {instance_id: {...}}
                instance_report = report.get(instance_id, {})
                result = parse_evaluation_results(
                    instance_report, instance_id, execution_time
                )

                # Set log directory
                log_dir = RUN_EVALUATION_LOG_DIR / run_id / "golden" / instance_id
                result.docker_logs = str(log_dir)

                if self.verbose:
                    console.print(result.get_summary())

                return result

            finally:
                # Cleanup temporary files
                predictions_path.unlink(missing_ok=True)
                dataset_path.unlink(missing_ok=True)

        except ValidationError as e:
            # Convert validation errors to ValidationResult for consistent handling
            execution_time = time.time() - start_time
            return ValidationResult(
                instance_id=instance_id,
                success=False,
                errors=[f"Validation error: {str(e)}"],
                execution_time=execution_time,
            )
        except Exception as e:
            # Wrap other exceptions
            execution_time = time.time() - start_time
            error_trace = traceback.format_exc()

            return ValidationResult(
                instance_id=instance_id,
                success=False,
                errors=[f"Evaluation failed: {str(e)}", error_trace],
                execution_time=execution_time,
            )

    def validate_multiple(
        self, data_point_paths: List[Path]
    ) -> Dict[str, ValidationResult]:
        """
        Validate multiple data points.

        Args:
            data_point_paths: List of paths to data point JSON files

        Returns:
            Dictionary mapping instance_id to ValidationResult
        """
        results = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Validating {len(data_point_paths)} data points...",
                total=len(data_point_paths),
            )

            for i, path in enumerate(data_point_paths):
                try:
                    progress.update(
                        task,
                        description=f"[{i+1}/{len(data_point_paths)}] Validating {path.stem}...",
                    )
                    result = self.validate_single(path)
                    results[result.instance_id] = result
                except ValidationError as e:
                    console.print(f"[red]✗[/red] {path.stem}: {str(e)}")
                    results[path.stem] = ValidationResult(
                        instance_id=path.stem,
                        success=False,
                        errors=[str(e)],
                    )
                except Exception as e:
                    console.print(
                        f"[red]✗[/red] {path.stem}: Unexpected error: {str(e)}"
                    )
                    results[path.stem] = ValidationResult(
                        instance_id=path.stem,
                        success=False,
                        errors=[f"Unexpected error: {str(e)}"],
                    )

                progress.update(task, advance=1)

        return results

    def find_data_points(self, pattern: Optional[str] = None) -> List[Path]:
        """
        Find data point files in the data points directory.

        Args:
            pattern: Optional glob pattern to filter files

        Returns:
            List of data point file paths
        """
        if pattern:
            files = list(self.data_points_dir.glob(pattern))
        else:
            files = list(self.data_points_dir.glob("*.json"))

        # Filter out any non-data point files
        files = [f for f in files if f.is_file() and not f.name.startswith(".")]

        return sorted(files)
