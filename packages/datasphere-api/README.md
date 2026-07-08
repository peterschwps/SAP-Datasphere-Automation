# Datasphere-API

[![PyPI](https://img.shields.io/pypi/v/Datasphere-API?label=PyPI)](https://pypi.org/project/Datasphere-API/)
[![Python](https://img.shields.io/pypi/pyversions/Datasphere-API?label=Python)](https://pypi.org/project/Datasphere-API/)
[![CI](https://github.com/peterschwps/SAP-Datasphere-API/actions/workflows/ci.yml/badge.svg)](https://github.com/peterschwps/SAP-Datasphere-API/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Unofficial async Python client for the SAP Datasphere automation APIs.
This library powers the
[SAP-Datasphere-CLI](https://github.com/peterschwps/SAP-Datasphere-CLI)
and can be used to build your own automations (e.g. MCP servers or
scheduled jobs).

> [!NOTE]
> This project is not affiliated with, endorsed by, or supported by SAP.
> It uses the same internal HTTP endpoints as the SAP Datasphere web UI,
> which may change without notice.

## Features

- **Views**: export view analytics (persistence candidates), search
  views by attribute, persist/unpersist views, create/remove partitions,
  lock/unlock partitions.
- **Remote Tables**: list tables with statistics information,
  create/update statistics (Record Count / Simple / Histogram), refresh
  statistics.
- **Task Chains**: run task chains and wait for their completion.
- **Analytical Models**: export models with all their views (optionally
  per space), measure view persistence runtimes.
- **OAuth login included**: interactive authorization code flow via a
  real Chrome/Edge window (Playwright) with automatic token refresh and
  a shared token cache.

## Installation

```bash
uv add datasphere-api
# or
pip install datasphere-api
```

The interactive login drives an installed Chrome or Edge browser via
Playwright channels — a regular Chrome/Edge installation is required,
no `playwright install` download is needed.

## Quickstart

```python
import asyncio

from datasphere_api import DatasphereClient, DatasphereConfig


async def main() -> None:
    config = DatasphereConfig(
        base_url="https://example.eu10.hcs.cloud.sap",
        authorization_url=(
            "https://example.authentication.eu10.hana.ondemand.com"
            "/oauth/authorize"
        ),
        token_url=(
            "https://example.authentication.eu10.hana.ondemand.com"
            "/oauth/token"
        ),
        client_id="...",
        client_secret="...",
    )
    client = DatasphereClient(config)
    try:
        await client.login()
        success, log_details = await client.task_chains.run(
            "MY_CHAIN", "MY_SPACE"
        )
        print(success, log_details.get("runTime"))
    finally:
        await client.aclose()


asyncio.run(main())
```

The URLs and credentials can be found in your tenant under
System > Administration (Tenant Links and App Integration). The OAuth
client has to be of type "Interactive Usage" with the redirect URI
`http://localhost:8080`.

## Authentication

`client.login()` first tries to refresh cached tokens from the token
store (`session.json` in the user data directory of `Datasphere`). If no
tokens are cached or the refresh fails, a browser window opens for the
interactive login. All consumers of this library share the same token
cache, so a login in one tool also benefits the others.

## Layered results

The library is deliberately thin and works on two levels:

- **Endpoint methods**: one method = one HTTP call, acting as an
  unofficial documentation of the internal Datasphere API (e.g.
  `views.get_partitioning()`, `views.start_persistence()`,
  `remote_tables.create_statistics()`). They return the parsed
  payload or a small typed outcome.
- **Single-entity workflows**: minimal compositions of endpoint calls
  that every consumer needs identically — mostly start-and-poll flows
  like `views.persist_view()`, `views.analyze_view()` or
  `task_chains.run()`.

Batching, concurrency, retries across many entities and file output
are intentionally **not** part of this library — consumers like the
[SAP-Datasphere-CLI](https://github.com/peterschwps/SAP-Datasphere-CLI)
implement their own loops on top. For anything not covered,
`client.session` is the authenticated `httpx.AsyncClient` — you can
call any endpoint directly.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```

## License

[MIT](LICENSE)
