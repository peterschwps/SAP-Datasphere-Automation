import asyncio
import http.server
import json
import os.path
import socketserver
import sys
import threading
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from urllib.parse import parse_qs, quote, urlparse

import httpx
from playwright.async_api import async_playwright

from utils.filehandler import DATA_DIR, SESSION_FILE, settings
from utils.logging import logger

# Settings
DATASPHERE_URL: str = settings["Setup"]["DATASPHERE_URL"]
AUTHORIZATION_URL: str = settings["Setup"]["AUTHORIZATION_URL"]
TOKEN_URL: str = settings["Setup"]["TOKEN_URL"]
BROWSER_TO_USE: str = settings["Setup"]["BROWSER_TO_USE"].upper()
CLIENT_ID: str = settings["Credentials"]["CLIENT_ID"]
REDIRECT_URI: str = settings['Credentials']['REDIRECT_URI']

# Mapping of BROWSER_TO_USE to webdriver classes
BROWSER_MAPPING = {
    "CHROME": "chrome",
    "EDGE": "msedge",
}


class DatasphereAutomation:
    def __init__(self):
        self.session: httpx.AsyncClient = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
        )

    async def initialize_datasphere_session(self) -> httpx.AsyncClient:
        """
        Initializes the Datasphere session for all other methods.
        Loads cookies from COOKIES_FILE if it exists or
        initializes a new login.

        Deletes the cookie file and exits the program if an error
        occurs.

        Returns:
            httpx.AsyncClient: Initialized Datasphere session.
        """

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/"
                    "537.36 (KHTML, like Gecko) Chrome/138.0.0.0 "
                    "Safari/537.36 Edg/138.0.0.0"
                ),
                "Accept": "text/plain, */*; q=0.01",
                "Accept-Encoding": "gzip, deflate, zstd",
                "Accept-Language": "en",
            }
        )

        # Load session tokens if file exists
        if os.path.isfile(SESSION_FILE):
            logger.info("Loading session tokens...")
            with open(DATA_DIR / "session.json") as session_file:
                try:
                    tokens = json.load(session_file)
                except json.decoder.JSONDecodeError:
                    logger.critical("Unknown error. Deleting file...")
                    if os.path.isfile(SESSION_FILE):
                        os.remove(SESSION_FILE)
                    logger.error("Please restart the program.")
                    sys.exit(1)

                # Refresh tokens
                auth = httpx.BasicAuth(
                    username=CLIENT_ID,
                    password=os.environ.get("SECRET", ""),
                )
                response = await self.session.post(
                    url=TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                    },
                    auth=auth,
                )

                # Add tokens to session and store new tokens
                tokens = response.json()
                self.session.headers.update(
                    {"Authorization": f"Bearer {tokens['access_token']}"}
                )
                with open(SESSION_FILE, "w") as session_file:
                    json.dump(tokens, session_file)

                return self.session

        # If no cookies were found
        else:
            logger.debug("No cookies found.")

        # Start authentication/refresh
        await self._start_authentication()
        return self.session

    
    async def _start_authentication(self):

        class ReusableServer(socketserver.TCPServer):
            allow_reuse_address = True  # to allow immediate reuse of the port

        # Mutable container to store the callback code and access it from 
        # different threads
        callback: dict[str, str | None] = {"code": None}
        
        # Async handling of the callback server using an event to signal when
        # the code is received
        loop = asyncio.get_running_loop()
        received = asyncio.Event()

        @contextmanager
        def callback_server(port=8080):
            """
            Context manager for the callback server. Everything before the
            yield is treated as __enter__. Everything after the yield is
            treated as __exit__.

            Args:
                port (int, optional): Port to listen on. Defaults to 8080.

            Yields:
                dict[str, str | None]: Mapping of the callback code received in
                                       a GET-request. The key is 'code'. The
                                       initial value is None.
            """
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    """
                    Checks the query params of an incoming GET-request for a 
                    'code' parameter. Assigns the value to the 'code' key in
                    the callback dict amd displays a short confirmation in the
                    browser.
                    """
                    params = parse_qs(urlparse(self.path).query)
                    callback_code = params.get("code", [None])[0]
                    if callback_code:
                        callback["code"] = callback_code
                        self.send_response(200)
                        self.send_header(
                            "Content-Type",
                            "text/html; charset=utf-8",
                        )
                        self.end_headers()
                        self.wfile.write(
                            b"<h1>Code received</h1>"
                            b"<p>This window will be closed automatically.</p>"
                        )
                        loop.call_soon_threadsafe(received.set)

                def log_message(self, *args, **kwargs):
                    """
                    Overrides the default logs to hide output to the console.
                    """
                    return

            # Starts server in separate thread to not block the main thread
            with ReusableServer(("localhost", port), Handler) as server:
                thread = threading.Thread(
                    target=server.serve_forever,
                    daemon=True,
                )
                thread.start()
                try:
                    yield callback
                finally:
                    server.shutdown()
                    thread.join(timeout=3)

        # Start callback server and open Playwright browser for authentication
        with callback_server():
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel=BROWSER_MAPPING[BROWSER_TO_USE],
                    headless=False,
                )
                page = await browser.new_page()
                await page.goto(
                    f"{AUTHORIZATION_URL}"
                    f"?response_type=code"
                    f"&client_id={quote(CLIENT_ID)}"
                    f"&redirect_uri={quote(REDIRECT_URI)}"
                )

                # Wait about 2 minutes for the user to complete the login
                await asyncio.wait_for(received.wait(), timeout=120)

        # Send callback code to token endpoint to receive access tokens
        auth = httpx.BasicAuth(
            username=CLIENT_ID,
            password=os.environ.get("SECRET", ""),
        )
        response = await self.session.post(
            url=TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": callback["code"],
                "redirect_uri": REDIRECT_URI,
            },
            auth=auth,
        )

        # Add tokens to session and store new tokens
        tokens = response.json()
        self.session.headers.update(
            {"Authorization": f"Bearer {tokens['access_token']}"}
        )
        with open(SESSION_FILE, "w") as session_file:
            json.dump(tokens, session_file)

    async def run_async_tasks(
        self, items: Iterable, function: Callable, thread_count: int = 1
    ) -> None:
        """
        Executes the given function. 'Parallelizes' the tasks if the
        thread count is greater than 1.

        Args:
            items (list): List of all arguments to be passed to the function.
            function (Callable): Function to be executed.
            thread_count (int, optional): Amount of concurrent asynchronous
                                          tasks. Default is 1.
        """
        if thread_count > 1:
            semaphore = asyncio.Semaphore(thread_count)
            tasks = []
            for item in items:

                async def process_item(item):
                    async with semaphore:
                        if isinstance(item, list | tuple):
                            await function(*item)
                        else:
                            await function(item)

                task = asyncio.create_task(process_item(item))
                tasks.append(task)
            await asyncio.gather(*tasks)

        else:
            for item in items:
                if isinstance(item, list | tuple):
                    await function(*item)
                else:
                    await function(item)
