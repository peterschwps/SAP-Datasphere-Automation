# Repository Style Guide

## Scope and Authority

Use this guide for new and changed code, tests, configuration, and
handwritten documentation in both workspace packages.

- Write documentation, docstrings, comments, and user-facing messages in
  concise English.
- Checked-in configuration and contract tests take precedence if this guide
  drifts from them.
- Follow established local patterns where this guide is silent. Historical
  exceptions are not templates for new work or unrelated restyling.

## Formatting and Imports

- Target Python 3.12 or newer.
- Use four spaces, UTF-8, LF line endings, and a final newline.
- Keep Python code, comments, and docstrings within 79 columns where
  practical.
- Use Ruff only as a linter. `ruff check --fix` is allowed; never run
  `ruff format` or apply Black formatting.
- Prefer double-quoted strings and triple-double-quoted docstrings.
- Wrap multiline calls, signatures, imports, and literals in parentheses.
  Put one item per line when expanded and include a trailing comma.
- Separate top-level definitions with two blank lines, methods with one, and
  logical stages inside functions with blank lines.
- Group imports as standard library, third party, and project imports. Use
  absolute project imports and let Ruff maintain their order.
- Import runtime collection interfaces such as `Callable`, `Iterable`, and
  `Mapping` from `collections.abc`.
- Keep lint suppressions narrow and obvious. Indivisible external keys, URLs,
  generated literals, and intentional text art may justify a local exception.

For non-Python files, follow [EditorConfig](../.editorconfig) and the nearby
file. Preserve established layout instead of reformatting unrelated content.

## Typing, Naming, and Models

- Fully annotate production functions and methods, including `-> None`.
- Use built-in generics, `|` unions, PEP 695 generic syntax and `type`
  aliases, and `Self` for methods returning their instance type.
- Use `Protocol` for structural interfaces and `TypedDict` for known file or
  wire shapes.
- Restrict `Any`, incomplete containers, `cast`, and type suppressions to
  genuinely dynamic framework or external-data boundaries.
- Use rule-specific suppressions with a short reason when practical.
- Use `snake_case` for modules, functions, methods, and variables;
  `PascalCase` for classes and protocols; and `UPPER_SNAKE_CASE` for constants
  and enum members.
- Prefix private implementation helpers and private constants with `_`.
  Framework-prescribed names remain unchanged.
- Follow the established `ThingRequest`, `ThingResult`, `ThingStatus`,
  `ThingBatchRequest`, `ThingBatchResult`, and `ThingRecord` families.
- Use frozen, slotted dataclasses for immutable Core requests, results, and
  configuration values. Use tuples for immutable ordered collections.
- Use Pydantic for application settings. Keep exact external field names only
  at serialization and wire boundaries.
- Validate model invariants in `__post_init__` or a shared validator rather
  than scattering the same check across callers.

## Architecture, Errors, and Logging

- Keep presentation, terminal behavior, and file adaptation in
  `datasphere_cli`. Keep reusable commands, models, session handling, and
  tenant access in `datasphere_core`.
- Implement Core commands as typed async functions accepting a
  `CommandContext` and a request object and returning a typed result.
- Decorated command handlers must not send HTTP requests directly. Put each
  endpoint interaction in a focused helper function.
- Preserve command metadata, registry entries, public names, result files,
  import-side-effect guarantees, bounded concurrency, and input ordering.
- Represent expected domain outcomes with typed statuses. Raise `ValueError`
  for ordinary model invariants and the exceptions from
  `datasphere_core.errors` for command, session, and infrastructure failures.
- Catch narrow exceptions by default. Broad catches belong only at deliberate
  resilience, reporting, or cleanup boundaries and need a clear reason.
- Preserve cancellation semantics and exception causes deliberately.
- Create module loggers with `logging.getLogger(__name__)` and use lazy `%`
  interpolation for values. Never use f-strings in logger calls.
- Keep Core silent unless its consumer configures handlers. Do not add tokens,
  secrets, or other sensitive values to ordinary application logs. The
  explicitly enabled HTTP diagnostic log is a separate subsystem.

See the [Datasphere-Core execution architecture](datasphere-core-execution.md)
for the command lifecycle and package boundary.

## Docstrings

- Do not add module-level docstrings. Document symbols instead.
- Give new production classes, functions, methods, properties, and meaningful
  nested callbacks a docstring. Tiny self-evident local fakes or framework
  implementation classes may omit one.
- Put triple quotes on their own lines.
- Start function and method summaries with a present-tense third-person verb,
  such as “Builds,” “Loads,” “Returns,” or “Validates.”
- Describe classes and data containers with concise noun phrases.
- Describe behavior, contracts, and non-obvious guarantees rather than visible
  implementation steps or internal layer names.
- Use Google-style `Args:`, `Raises:`, `Returns:`, and `Yields:` sections only
  when they add information. Order `Raises:` before `Returns:` or `Yields:`.
- Repeat parameter and return types as they appear in annotations. Mark
  optional parameters and state defaults concisely.
- Align wrapped descriptions when this remains readable. If a long type leaves
  too little room, place the description on the next indented line.
- Use complete sentences with terminal punctuation. Keep simple properties and
  parameterless methods to a short summary plus only necessary sections.
- Place dataclass fields and enum members directly after the class docstring.

```python
def load_records(path: Path, limit: int | None = None) -> list[Record]:
    """
    Loads validated records from one file.

    Args:
        path (Path): File to read.
        limit (int | None, optional): Maximum number of records to return.
                                      Defaults to None.

    Raises:
        ValueError: If a record is invalid.

    Returns:
        list[Record]: Validated records in file order.
    """
```

## Comments

- Write comments in English and place them immediately before the statement or
  block they explain.
- Use short section comments to make the logical stages of a longer function
  visible.
- Explain rationale, ordering constraints, external quirks, defensive code,
  concurrency, or cleanup invariants. Avoid narrating code that is already
  clear.
- A section label may be followed by one short reason. Move longer explanations
  into a docstring or architecture document.
- Do not repeat the current function's docstring or another callable's public
  contract.
- Do not use decorative separator comments. Split an overgrown module instead.
- Use prefixes such as `IMPORTANT:` sparingly and only for real hazards.
- In tests, put a useful rationale directly before the assertion or setup it
  protects. Do not require `Arrange`/`Act`/`Assert` labels.

## Tests

- Keep CLI tests in `tests/` and Core tests in
  `packages/datasphere-core/tests/`.
- Name tests `test_<behavior>` and give each test a short docstring beginning
  with “Checks that”.
- Use `Args:` in parameterized test docstrings when the parameters need
  explanation.
- Use plain `async def`; pytest's configured asyncio auto mode supplies the
  integration.
- Annotate test return values and project-owned helpers and fixtures. Built-in
  or plugin fixture parameters may follow the established local convention.
- Separate setup, action, and assertions with blank lines.
- Mock HTTP at the transport boundary with `respx` and real `httpx.Response`
  objects. Use `monkeypatch`, `tmp_path`, `capsys`, and `caplog` at their
  respective seams.
- Prefer exact assertions for requests, results, statuses, ordering, filenames,
  output, and side effects. Preserve architecture and public-contract guard
  tests.
- Keep local fakes small and close to the test that uses them.
- Do not introduce a coverage requirement without a separate policy decision.

## Documentation

- Use concise English, ATX headings, language-tagged code fences, and
  repository-relative links.
- Wrap prose near 79 columns where practical. Tables, URLs, and other
  indivisible content may exceed it.
- Do not commit machine-local paths, private context, unrelated project
  references, or credentials.
- Treat `CHANGELOG.md` and release notes as generated output, not as a template
  for handwritten Markdown.

## Validation

Use the checks in [Developer Setup](SETUP.md) that apply to the changed files.
Pyright is a configured local check but is not currently a CI gate. Build all
packages only when packaging or workspace behavior changes. Never add
`ruff format` to the validation workflow.

The technical sources of truth are the
[project configuration](../pyproject.toml), the
[Core package configuration](../packages/datasphere-core/pyproject.toml),
[EditorConfig](../.editorconfig), the
[pre-commit configuration](../.pre-commit-config.yaml), and the
[CI workflow](../.github/workflows/ci.yml).
