# Developer Setup

Run all commands from the repository root. [uv](https://docs.astral.sh/uv/)
manages Python, the virtual environment, dependencies, workspace packages,
and command execution.

## Install

Install uv, then synchronize both packages and the development dependencies:

```bash
uv sync --all-packages --group dev
```

The pre-commit environments currently require Python 3.12. Install it through
uv if it is not already available:

```bash
uv python install 3.12
```

Install the file and commit-message hooks:

```bash
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg
```

Interactive authentication uses the Chrome or Edge channel selected in the
application settings. Install that browser through Playwright when needed:

```bash
uv run playwright install chrome  # or msedge
```

## Tools and Checks

- [Ruff](https://docs.astral.sh/ruff/) checks lint and import rules. It is not
  used as a formatter.
- [Pyright](https://microsoft.github.io/pyright/) provides the configured local
  type check.
- [pytest](https://docs.pytest.org/) runs both test suites.
- [Hatchling](https://hatch.pypa.io/latest/config/build/) builds both packages
  through uv.
- [pre-commit](https://pre-commit.com/) runs file hygiene, Ruff fixes,
  Conventional Commit validation, and Gitleaks.
- [EditorConfig](https://editorconfig.org/) and the Markdownlint configuration
  provide editor guidance without a repository-wide validation command.

Run the checks relevant to the change:

```bash
uv run ruff check .
uv run pyright
uv run pytest
uv build --all-packages
uv run pre-commit run --all-files
```

CI runs Ruff, pytest, and the workspace build. Pyright and the complete
pre-commit suite are configured local checks. Pre-commit may modify files
because some hooks apply fixes. Never run `ruff format`.

## Textual Development

Run the Textual console and application in separate terminals:

```bash
uv run textual console
```

```bash
uv run textual run --dev -c datasphere
```

Tool versions and exact configuration live in
[`.python-version`](../.python-version),
[`pyproject.toml`](../pyproject.toml), [`uv.lock`](../uv.lock),
[`.pre-commit-config.yaml`](../.pre-commit-config.yaml),
[EditorConfig](../.editorconfig),
[Markdownlint](../.markdownlint.json), and the
[CI workflow](../.github/workflows/ci.yml). GitHub Actions, Commitlint, and
Release Please require no separate local setup.
