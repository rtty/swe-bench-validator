"""
SWE-bench Data Point Validator

A command-line tool for validating SWE-bench data points using the official
SWE-bench evaluation harness and Docker-based testing environment.
"""

__version__ = "0.1.0"

from .cli import main
from .result_parser import ValidationResult
from .validator import SWEBenchValidator

__all__ = ["SWEBenchValidator", "ValidationResult", "main"]
