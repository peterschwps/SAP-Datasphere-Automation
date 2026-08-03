# Datasphere-Core Execution Architecture

`datasphere-core` is the presentation-independent command layer shared by the
CLI and the planned MCP adapter.

Core owns typed requests and results, the command registry, the requests it
sends to the tenant, lifecycle and progress reporting, bounded concurrency,
batch summaries, and local session and credential handling.

Core does not own Textual or Rich state, CSV and JSON file formats, terminal
rendering, MCP protocol objects, or process exit handling.

## Calling a Command

Every command is a plain async function. Adapters import it and call it
directly — there is no dispatcher and no registry lookup in the call path:

```python
from datasphere_core import CommandContext
from datasphere_core.commands.views import persist_view_batch
from datasphere_core.models.views import (
    PersistViewBatchRequest,
    PersistViewRequest,
)

result = await persist_view_batch(
    CommandContext(client=session.client),
    PersistViewBatchRequest(
        requests=(PersistViewRequest(view="V_SALES", space="DEV"),),
        max_concurrency=4,
    ),
)
```

The call path is:

```text
adapter
  -> persist_view_batch            (lifecycle reporting)
  -> _persist_view_batch           (command body)
  -> run_batch                     (concurrency + item reporting)
  -> _persist_view                 (one item)
  -> run_persistence               (start the run, poll its task log)
  -> _start_view_activity          (the HTTP request itself)
```

## Anatomy of a Command

Every command is one decorated async function. `command()` marks a single
command, `batch_command()` marks a batch command. Both report `started`, run
the body, and report the terminal phase:

```python
@command(PERSIST_COMMAND_NAME)
async def persist_view(context, request) -> PersistViewResult:
    ...


@batch_command(PERSIST_BATCH_COMMAND_NAME)
async def persist_view_batch(context, request) -> PersistViewBatchResult:
    results, summary = await run_batch(
        context,
        PERSIST_BATCH_COMMAND_NAME,
        request.requests,
        persist_view,
        max_concurrency=request.max_concurrency,
    )
    return PersistViewBatchResult(results=results, summary=summary)
```

A batch passes its sibling command to `run_batch()`, which applies it to every
item with bounded concurrency and reports each completed item. `run_batch()`
runs the items with their progress muted, so a batch reports its own
`advanced` updates instead of one nested command lifecycle per item.

Where the per-item work is not a command of its own — for example because the
batch fetches shared metadata once — the operation is a plain private function
instead (`_configure_statistics_item`, `_resolve_dependencies`).

## Statuses and Outcomes

Every command result has a `status`. Status enums inherit from `CommandStatus`
and each member declares the `Outcome` it belongs to:

```python
class PersistViewStatus(CommandStatus):
    COMPLETED = "completed", Outcome.SUCCEEDED
    START_FAILED = "start_failed", Outcome.FAILED
    FAILED = "failed", Outcome.FAILED
    TIMED_OUT = "timed_out", Outcome.TIMED_OUT
```

The outcome drives both batch accounting and the terminal lifecycle phase, so
no command needs its own classification function.

| Outcome | Batch counter | Terminal phase |
| --- | --- | --- |
| `SUCCEEDED` | `succeeded` | `completed` |
| `SKIPPED` | `skipped` | `completed` |
| `FAILED` | `failed` | `failed` |
| `TIMED_OUT` | `timed_out` | `timed_out` |

A skipped item is not a failure — "already persisted" or "no partitions" means
there was nothing to do.

## Progress and Batch-Item Results

`CommandContext` carries two optional callbacks. Both are ignored when not
supplied, so Core works the same with and without a UI.

`progress_callback` receives `CommandProgress`:

- `started` once, before the body runs. It carries no counters — for
  discovery-based batches the item count is not known yet.
- `advanced` once per completed batch item, carrying the running counters,
  `total_items`, and the `item_index`.
- exactly one terminal phase: `completed`, `failed`, `timed_out`, or
  `cancelled`.

Consumers that size a progress bar should read `total_items` from the first
`advanced` event.

`batch_item_result_callback` receives `BatchItemResult` for every completed
batch item, including the command-specific result object. The CLI uses it to
checkpoint long measurement runs to disk while the batch is still running.

Every item is reported the moment it completes, never bundled at the end —
that is what makes the checkpoint useful when a long run is interrupted.
`item_index` always refers to the position in the batch input, but the order in
which items arrive depends on the command:

| Command | Reporting order | Why |
| --- | --- | --- |
| Most batches | completion order | each item has its own operation and is reported when it returns |
| `analytical_models.measure_view_persistence_batch` | completion order | the work runs per view, so a model completes with the last view it depends on — possibly one measured for another model |
| `analytical_models.get_view_dependencies_batch` with `deduplicate_views` | input order | deduplication keeps the first occurrence, so a model only completes once every earlier model is resolved |

Consumers that need the input order should sort by `item_index` rather than
rely on arrival order.

`run_batch()` covers the common case: one operation per item, reported when it
returns. The two analytical-model commands have no such per-item operation and
drive a `BatchReporter` themselves, which is the same bookkeeping `run_batch()`
uses internally.

One limit remains: a model that depends on fifty views stays unreported until
the last of them is measured. Finer granularity would require view results to
become batch items of their own.

## Concurrency and Ordering

`run_batch()` bounds concurrency with a semaphore and gathers the results, so
they always keep the input order regardless of completion order. If any item
raises, the remaining items are cancelled before the exception propagates.

`execute_with_concurrency_limit()` offers the same bounded execution without
progress reporting. It is used for internal fan-out, for example measuring
each unique physical view exactly once.

`max_concurrency` is validated against `MAXIMUM_BATCH_CONCURRENCY` (32) to
protect the Datasphere tenant.

## Errors and Cancellation

Core does not swallow errors. Expected domain outcomes become a status;
everything else propagates:

- **Timeouts** of a remote operation become a `TIMED_OUT` status carrying the
  Datasphere log ID, so the caller can follow the run that may still be going.
- **Cancellation** after a remote start raises `CommandCancelledError` (a
  subclass of `asyncio.CancelledError`) carrying the log ID.
- **Anything else** propagates unchanged after a `failed` phase was reported.

The persistence measurement shields its cleanup: if the surrounding command is
cancelled after a view was persisted, the cleanup still runs so the view does
not stay persisted.

## Validation

Only values that are genuinely dangerous are validated: operation timeouts,
`max_concurrency`, the partition year range, the client secret, and an
ambiguous analytical-model selection. Everything else is left to the type
checker — Core is built for correct callers, and robustness work is deferred
until the CLI runs on top of it.

## Registry

`COMMANDS` maps every command name to a `CommandDefinition` holding its
request and result type, handler, description, timeouts, and the `read_only`,
`destructive`, `idempotent`, and `expose_to_mcp` flags. It is metadata only —
used for CLI help text and the planned MCP exposure, never in the call path.

Command names are validated at import time to catch registry typos.

## Module Map

| Module | Contents |
| --- | --- |
| `execution.py` | `command`, `batch_command`, `run_batch`, `BatchReporter`, `execute_with_concurrency_limit` |
| `context.py` | `CommandContext` and its callbacks |
| `models/common.py` | `CommandStatus`, `Outcome`, `CommandProgress`, `BatchSummary` |
| `models/<domain>.py` | Requests, results, and status enums per domain |
| `commands/<domain>.py` | Command bodies and their `CommandDefinition`s |
| `conversion.py` | Normalizing Datasphere log IDs, statuses, and runtimes |
| `errors.py` | `CommandError` and its subclasses |
| `definitions.py`, `registry.py` | Command metadata and the registry |
| `auth.py`, `credentials.py` | Session handling and the OS credential store |
