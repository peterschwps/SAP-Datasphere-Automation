# Contributing

Contributions from people and coding agents are welcome. Before changing code,
tests, configuration, or documentation, read the
[repository style guide](docs/STYLE.md) and
[developer setup](docs/SETUP.md). Checked-in configuration and tests take
precedence if either guide drifts.

## Branches and Commits

- Name branches `<type>/<lowercase-slug>`, for example
  `docs/add-contributing-guide`.
- Use one of these types: `feat`, `fix`, `chore`, `docs`, `style`, `refactor`,
  `perf`, `test`, `build`, `ci`, or `revert`.
- Write commits in Conventional Commit form:
  `<type>[optional scope][!]: <description>`.
- Mark breaking changes with `!` or a `BREAKING CHANGE:` footer.

## Changes and Checks

- Keep changes focused and avoid unrelated restyling.
- Add or update tests and documentation when behavior or public contracts
  change.
- Run the checks relevant to the changed files as described in
  [Developer Setup](docs/SETUP.md#tools-and-checks).
- CI checks Ruff, pytest, the workspace build, commit messages, and branch
  names. Pyright and the complete pre-commit suite are configured local checks.

## Pull Requests

- Open pull requests against `main`.
- Summarize what changed, why it changed, and which checks were run.
- Keep each pull request reviewable and limited to one coherent change.

## Generated and Sensitive Files

- During an ordinary contribution, do not edit `CHANGELOG.md`, release notes,
  the release manifest, or package versions, and do not create release tags.
  Release Please derives them from commits merged into `main`.
- Never commit or share a real `settings.toml`, credentials, client secrets,
  OAuth or session tokens, private tenant data, or the raw
  [HTTP diagnostic log](README.md#http-logging).
- Sanitize logs, screenshots, fixtures, examples, and command output before
  sharing them.
