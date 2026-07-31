from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

LAMBDA_DIRECT_UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024


def build_lambda_package(
    *,
    output_path: Path,
    requirements_path: Path,
    source_root: Path,
) -> dict[str, int | str]:
    """Build a Linux x86_64 Lambda ZIP without including local data artifacts."""
    resolved_output = output_path.resolve()
    resolved_requirements = requirements_path.resolve()
    resolved_source = source_root.resolve()
    if resolved_output.suffix != ".zip":
        raise ValueError("Lambda package output path must end with .zip.")
    if not resolved_requirements.exists():
        raise FileNotFoundError(f"Lambda requirements not found: {resolved_requirements}")
    package_source = resolved_source / "marygenai"
    if not package_source.exists():
        raise FileNotFoundError(f"MaryGenAI package source not found: {package_source}")

    build_root = resolved_output.parent
    package_root = build_root / "package"
    shutil.rmtree(package_root, ignore_errors=True)
    resolved_output.unlink(missing_ok=True)
    package_root.mkdir(parents=True)

    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(package_root),
            "--requirements",
            str(resolved_requirements),
            "--python-version",
            "3.13",
            "--python-platform",
            "x86_64-manylinux_2_28",
            "--only-binary",
            ":all:",
            "--require-hashes",
        ],
        check=True,
    )
    shutil.copytree(
        package_source,
        package_root / "marygenai",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    archive_base = resolved_output.with_suffix("")
    archive_path = Path(
        shutil.make_archive(str(archive_base), "zip", root_dir=package_root)
    ).resolve()
    archive_size = archive_path.stat().st_size
    if archive_size > LAMBDA_DIRECT_UPLOAD_LIMIT_BYTES:
        raise ValueError(
            f"Lambda ZIP is {archive_size} bytes, above the direct-upload limit of "
            f"{LAMBDA_DIRECT_UPLOAD_LIMIT_BYTES} bytes."
        )
    return {
        "output_path": str(archive_path),
        "size_bytes": archive_size,
        "architecture": "x86_64",
        "python_runtime": "python3.13",
    }
