"""DPK file repository management.

Handles PCM-style DPK repositories with structure:
    {repo_path}/{major}/{minor}/*.zip
Example:
    /cm_psft_dpks/dpk/linux/tools/862/04/PT862_1of5.zip
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class DpkVersion:
    """A DPK version found in the repository."""

    major: str
    minor: str
    path: Path
    zip_count: int
    total_size: int  # bytes

    @property
    def label(self) -> str:
        return f"{self.major}.{self.minor}"

    @property
    def human_size(self) -> str:
        if self.total_size >= 1_073_741_824:
            return f"{self.total_size / 1_073_741_824:.1f} GB"
        if self.total_size >= 1_048_576:
            return f"{self.total_size / 1_048_576:.1f} MB"
        return f"{self.total_size / 1024:.1f} KB"


class DpkRepo:
    """Interface to a PCM-style DPK file repository."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    def list_versions(self, filter_major: Optional[str] = None) -> List[DpkVersion]:
        """List all DPK versions in the repository.

        Args:
            filter_major: If set, only return versions matching this major version.

        Returns:
            Sorted list of DpkVersion (newest first by major.minor).
        """
        if not self.repo_path.is_dir():
            return []

        versions: List[DpkVersion] = []
        for major_dir in sorted(self.repo_path.iterdir(), reverse=True):
            if not major_dir.is_dir() or not major_dir.name.isdigit():
                continue
            if filter_major and major_dir.name != filter_major:
                continue
            for minor_dir in sorted(major_dir.iterdir(), reverse=True):
                if not minor_dir.is_dir() or not minor_dir.name.isdigit():
                    continue
                info = self.get_version_info(major_dir.name, minor_dir.name)
                if info.zip_count > 0:
                    versions.append(info)

        return versions

    def resolve_version(self, version: Optional[str] = None) -> Path:
        """Resolve a version string to a directory path.

        Args:
            version: "862.04" format, or None for latest.

        Returns:
            Path to the version directory containing zip files.

        Raises:
            FileNotFoundError: If version not found or repo empty.
        """
        if version:
            parts = version.split(".")
            if len(parts) != 2:
                raise ValueError(f"Invalid version format: {version} (expected MAJOR.MINOR)")
            major, minor = parts
            path = self.repo_path / major / minor
            if not path.is_dir():
                raise FileNotFoundError(f"Version {version} not found at {path}")
            zips = list(path.glob("*.zip"))
            if not zips:
                raise FileNotFoundError(f"No zip files in {path}")
            return path

        # No version specified - find latest
        versions = self.list_versions()
        if not versions:
            raise FileNotFoundError(f"No DPK versions found in {self.repo_path}")
        return versions[0].path

    def get_version_info(self, major: str, minor: str) -> DpkVersion:
        """Get info about a specific version.

        Args:
            major: Major version (e.g. "862")
            minor: Minor version (e.g. "04")

        Returns:
            DpkVersion with zip count and total size.
        """
        path = self.repo_path / major / minor
        zips = list(path.glob("*.zip")) if path.is_dir() else []
        total_size = sum(z.stat().st_size for z in zips)
        return DpkVersion(
            major=major,
            minor=minor,
            path=path,
            zip_count=len(zips),
            total_size=total_size,
        )
