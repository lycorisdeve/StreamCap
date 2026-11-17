# Dependency baseline (2026-11-12)

StreamCap requires Python 3.12 or newer. The application is validated on Python 3.12.
Direct dependencies are pinned to the latest stable releases checked for this update.
Transitive dependencies are resolved within their upstream compatibility constraints.

| Component | Version |
| --- | --- |
| Flet / CLI / desktop / Web / video | 1.1.2 |
| FastAPI | 0.162.5 |
| Starlette | 1.10.0 |
| Uvicorn | 0.54.0 |
| cachetools | 8.0.0 |
| deprecated | 3.0.1 |
| python-dotenv | 1.2.4 |
| Loguru | 0.8.0 |
| Pillow | 13.0.0 |
| Poetry build backend | 2.5.0 |
| Ruff | 0.17.4 |
| PyInstaller | 6.22.3 |
| dmgbuild (macOS only) | 1.6.7 |

StreamGet uses the current main commit
016a8d6fbef4f5f14c0ec986dc3528c5a22235ab. CI must not upgrade it again
after installing requirements; the tested revision must also be the packaged revision.
Docker uses Node.js 26 LTS. FFmpeg download scripts continue to use upstream
stable-release download endpoints.

## Install and validate

Use a project-specific environment instead of replacing unrelated global packages.
Create and activate .venv, then run:

    python -m pip install --upgrade pip
    python -m pip install --upgrade --upgrade-strategy eager -r requirements.txt -r requirements-dev.txt
    python -m pip check
    python -m unittest discover
    ruff check main.py app tests --config .ruff.toml
    ruff format --check main.py app tests --config .ruff.toml

For server-only installation, use requirements-web.txt instead of requirements.txt.
requirements-dev.txt contains lint/build tools and is not needed to run the application.

The test suite starts a real Web CLI subprocess and waits for HTTP 200.
This catches constructor/lifespan/Uvicorn failures that an in-process ASGI test can miss.
CI validates Linux Web and Windows desktop dependencies with fresh installations.

## Why Web dependency versions are explicit

Flet 0.85.3 forwarded the removed openapi_prefix argument to FastAPI. A fresh CI
installation selected a newer FastAPI and crashed before opening the HTTP port.
Flet 1.1.2 no longer forwards that argument. Pinning the tested Web stack avoids
silently changing it on the next build.

Update both requirements files and both dependency sections of pyproject.toml together.
Run the process-level Web test before publishing.

## Flet 1.x compatibility

Navigation now awaits Page.push_route, URL opening uses UrlLauncher, and login
persistence uses SharedPreferences. Home/about colors use the current BLACK_*
and WHITE_* names. Regression tests exercise home rendering in both themes and
screen layouts, navigation ordering, and login token persistence.

Desktop packaging caches Flet archives by client version and platform, so an
older cached client cannot be reused with upgraded Python packages.

Web smoke testing also covered home, recording dialogs, settings, storage, logs,
and about pages. Browser resizing now mounts the new layout and restores the
sidebar when returning to a wide viewport, while reusing the existing content.
