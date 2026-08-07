"""Builds a fully self-contained deployment package for the Functions app (function_app.py,
host.json, requirements.txt at repo root) and zips it to build/function-deploy.zip.

Why this exists, not just `az functionapp deploy`/`config-zip` with SCM_DO_BUILD_DURING_DEPLOYMENT=true:
live-verified in Phase 5 (docs/PROGRESS_LOG.md) that Azure's remote (Oryx) build does NOT
reliably work for this app -- across several attempts it either silently dropped files it hadn't
itself pip-installed (a hand-vendored greenlux_sentinel/ folder disappeared entirely) or wiped a
pre-placed .python_packages/lib/site-packages back to whatever requirements.txt alone produced,
even when requirements.txt still listed the missing package (pandas). The only approach that
actually worked: build everything locally, target the exact Linux platform Azure Functions runs
on, and deploy with remote build disabled entirely (SCM_DO_BUILD_DURING_DEPLOYMENT=false) so
nothing server-side touches the package.

Also live-verified: a single --platform tag does not work for every dependency. Different
packages publish wheels under different manylinux baselines (pandas needs manylinux_2_28;
psycopg-binary and pydantic-core only publish manylinux_2_17/manylinux2014) -- mixing tags across
packages is fine at runtime (a manylinux2014 wheel runs fine on a newer glibc host), it's purely
about which tag pip needs to be told to accept when *resolving* each package. Hence the multiple
install passes below rather than one `pip install -r requirements.txt --platform X` call.

Usage: python scripts/build_function_package.py
Then: az functionapp deployment source config-zip --name <app> --resource-group <rg> \\
        --src build/function-deploy.zip
(and confirm SCM_DO_BUILD_DURING_DEPLOYMENT / ENABLE_ORYX_BUILD app settings are both "false" --
see infra/README.md's Functions deployment section)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build" / "function_package"
SITE_PACKAGES = BUILD_DIR / ".python_packages" / "lib" / "site-packages"
ZIP_PATH = REPO_ROOT / "build" / "function-deploy.zip"

_PYTHON_TAG_ARGS = [
    "--python-version", "3.12",
    "--implementation", "cp",
    "--abi", "cp312",
    "--only-binary=:all:",
]

# Packages that only publish manylinux_2_17/manylinux2014-tagged wheels (older baseline) --
# psycopg-binary and pydantic-core (pulled in by pydantic-settings) specifically, confirmed live.
_MANYLINUX_2_17_PACKAGES = [
    ["psycopg[binary]>=3.2.10,<4"],
    ["pydantic-settings>=2.11.0,<3"],
]

# Everything else resolves fine under the newer manylinux_2_28 baseline.
_MANYLINUX_2_28_PACKAGES = [
    ["pandas>=2.3.3,<3"],
    [
        "azure-functions>=1.21.3,<2",
        "azure-cosmos>=4.9.0,<5",
        "azure-identity>=1.25.1,<2",
        "azure-keyvault-secrets>=4.10.0,<5",
        "azure-storage-blob>=12.24.0,<13",
        "httpx>=0.28.1,<1",
    ],
    # mcp's real runtime deps (`pip show mcp` on 1.29.0), everything but the Windows-only
    # pywin32 -- installed after mcp itself below (--no-deps). An earlier, guessed-at subset
    # (just starlette/sse-starlette/httpx-sse) missed jsonschema, live-verified in Phase 5:
    # cross_check_lu_entities() failed with ModuleNotFoundError('jsonschema') partway through a
    # real Function App run, well after the pandas-heavy loaders had already succeeded.
    [
        "jsonschema",
        "pydantic",
        "pyjwt",
        "python-multipart",
        "starlette",
        "sse-starlette",
        "httpx-sse",
        "typing-inspection",
        "uvicorn",
    ],
]

# mcp's own PyPI metadata declares pywin32 for sys_platform == "win32" -- a marker pip evaluates
# against *this* (Windows) host regardless of --platform, making the real dependency resolution
# fail for a package that doesn't even need pywin32 on Linux. --no-deps sidesteps it; its actual
# runtime deps are covered by _MANYLINUX_2_28_PACKAGES above.
_NO_DEPS_PACKAGES = ["mcp>=1.16.0,<2"]


def _pip_install(args: list[str], platform: str | None = None, no_deps: bool = False) -> None:
    cmd = [sys.executable, "-m", "pip", "install", *args, "--target", str(SITE_PACKAGES)]
    if platform:
        cmd += ["--platform", platform, *_PYTHON_TAG_ARGS]
    if no_deps:
        cmd.append("--no-deps")
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def main() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    SITE_PACKAGES.mkdir(parents=True)

    print("=== building greenlux_sentinel wheel ===")
    wheel_dir = REPO_ROOT / "build" / "wheel_out"
    if wheel_dir.exists():
        shutil.rmtree(wheel_dir)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheel_dir)],
        check=True, cwd=REPO_ROOT,
    )
    wheel_path = next(wheel_dir.glob("greenlux_sentinel-*.whl"))

    print("=== installing greenlux_sentinel itself (no-deps -- its deps are installed explicitly below) ===")
    _pip_install(["--no-deps", str(wheel_path)])

    print("=== installing mcp (no-deps -- see _NO_DEPS_PACKAGES comment) ===")
    for pkgs in [_NO_DEPS_PACKAGES]:
        _pip_install(pkgs, platform="manylinux_2_28_x86_64", no_deps=True)

    print("=== installing manylinux_2_17 packages ===")
    for pkgs in _MANYLINUX_2_17_PACKAGES:
        _pip_install(pkgs, platform="manylinux_2_17_x86_64")

    print("=== installing manylinux_2_28 packages ===")
    for pkgs in _MANYLINUX_2_28_PACKAGES:
        _pip_install(pkgs, platform="manylinux_2_28_x86_64")

    for name in ("host.json", "function_app.py"):
        shutil.copy(REPO_ROOT / name, BUILD_DIR / name)

    print(f"=== zipping to {ZIP_PATH} ===")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    skipped = []
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD_DIR.rglob("*"):
            if path.is_dir() or path.name == "__pycache__" or path.suffix == ".pyc":
                continue
            rel = path.relative_to(BUILD_DIR).as_posix()  # forward slashes -- see module docstring caveat below
            try:
                zf.write(path, rel)
            except OSError:
                # A handful of deeply-nested license files (numpy's, mainly) exceed Windows'
                # path-length limit on this build machine -- not needed at runtime, safe to skip.
                skipped.append(rel)

    if skipped:
        print(f"skipped {len(skipped)} long-path files (license/doc noise, not needed at runtime)")
    print(f"done: {ZIP_PATH}")


if __name__ == "__main__":
    main()
