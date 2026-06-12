"""Reusable report writer base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class MarkdownReport(ABC):
    """Base class for report generators that write Markdown files."""

    filename: str
    title: str

    def write(self, directory: Path, state: dict[str, Any]) -> Path:
        """Render the report into the target directory and return its path."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.filename
        path.write_text(self.render(state), encoding="utf-8")
        return path

    @abstractmethod
    def render(self, state: dict[str, Any]) -> str:
        """Return report Markdown."""
        raise NotImplementedError
