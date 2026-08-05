import tomllib
from pathlib import Path

from app import __version__


def test_package_and_runtime_versions_match():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"].replace("b", "-beta.") == __version__
