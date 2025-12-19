"""
SWE-bench Data Downloader

A command-line tool for downloading specific SWE-bench data points
using the official SWE-bench library and saving them to the local data_points/ folder.
"""

__version__ = "0.1.0"

from .cli import main
from .downloader import SWEBenchDownloader

__all__ = ["SWEBenchDownloader", "main"]
