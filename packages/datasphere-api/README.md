# Datasphere-API

Unofficial async Python client for the SAP Datasphere automation APIs.
This library powers the
[SAP-Datasphere-CLI](https://github.com/peterschwps/SAP-Datasphere-Automation)
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
        results = await client.task_chains.run(
            chains=[{"entity": "MY_CHAIN", "space": "MY_SPACE"}],
        )
        print(results)
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

The library returns data on two levels:

- **Curated results** (recommended): high-level operations like
  `views.persist_views()` or `remote_tables.create_statistics()` return
  small, typed result structures (see `datasphere_api.models`). Their
  keys intentionally match the CSV/JSON exports of the CLI.
- **Raw payloads**: low-level fetchers like `views.get_all_views()` or
  `remote_tables.get_all_tables()` return the parsed API payload, typed
  with broad TypedDicts. For anything not covered, `client.session` is
  the authenticated `httpx.AsyncClient` — you can call any endpoint
  directly.

Long-running batch operations accept an `on_result`/`on_update`
callback that is invoked after every finished item, so consumers can
save intermediate results during runs that take hours.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```

## License

[MIT](LICENSE)
