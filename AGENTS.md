# AGENTS.md

## Cursor Cloud specific instructions

Datasphere-CLI is a single-product **Textual TUI** (entry point `main.py` -> `datasphere_cli.cli.main`). There are no local services, web servers, or databases; at runtime it talks to a remote SAP Datasphere tenant over HTTPS. Standard install/lint/test/build commands live in [.github/workflows/ci.yml](.github/workflows/ci.yml) and [pyproject.toml](pyproject.toml).

- **Always use `--no-sources`.** `[tool.uv.sources]` in [pyproject.toml](pyproject.toml) links `datasphere-api` to a local editable path (`../SAP-Datasphere-API`) that does not exist in the cloud VM. A plain `uv sync` fails; `--no-sources` resolves `datasphere-api` from PyPI instead. This applies to every uv invocation, e.g. `uv sync --no-sources`, `uv run --no-sources pytest`, `uv run --no-sources --with ruff ruff check .`, `uv run --no-sources pyright .`.
- **`uv sync --no-sources` rewrites `uv.lock`** in the working tree (editable path source -> PyPI source). Do not commit that change.
- **Running the TUI:** `uv run --no-sources python main.py`. On first launch, if `~/.config/Datasphere/settings.toml` is missing, the app writes a template and immediately exits (`create_settings_file` -> `sys.exit()` in [src/datasphere_cli/utils/settings.py](src/datasphere_cli/utils/settings.py)). Create/fill that file with tenant URLs and an OAuth `client_id` before the app will start into the menu. The TUI enforces `MIN_WIDTH = 112`, so use a wide terminal.
- **Real actions need real credentials.** Executing a menu action performs an OAuth browser login via Playwright (redirect callback on `http://localhost:8080`) against a live SAP Datasphere tenant; the client secret can be supplied via the `SECRET` env var. Without a real tenant + OAuth client, only launching/navigating the TUI works, not executing actions.
- **Tests need nothing external.** The suite is fully mocked (no network, tenant, Playwright browsers, or port 8080). Run with `uv run --no-sources pytest`.
