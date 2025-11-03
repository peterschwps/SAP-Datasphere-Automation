import asyncio
import json
import os.path
import re
import sys
from collections.abc import Callable, Iterable
from random import randint
from time import sleep, time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from rich import get_console
from rich.prompt import Prompt
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.abstract_event_listener import (
    AbstractEventListener,
)
from selenium.webdriver.support.event_firing_webdriver import (
    EventFiringWebDriver,
)
from selenium.webdriver.support.wait import WebDriverWait

from utils.filehandler import COOKIES_FILE, DATA_DIR, settings
from utils.logging import logger

# Important conditions from settings
URL_TO_USE: str = settings["Setup"]["URL_TO_USE"]
AUTHENTICATION_METHOD: str = settings["Setup"]["AUTHENTICATION_METHOD"]
BROWSER_TO_USE: str = settings["Setup"]["BROWSER_TO_USE"]

# Mapping of BROWSER_TO_USE to webdriver classes
BROWSER_MAPPING = {
    "CHROME": {
        "driver": webdriver.Chrome,
        "options": webdriver.ChromeOptions,
    },
    "EDGE": {
        "driver": webdriver.Edge,
        "options": webdriver.EdgeOptions,
    },
    "PLAYWRIGHT": None,
}

# Important URLs from settings
DATASPHERE_URL: str = settings["URLs"][URL_TO_USE]
SUBDOMAIN: str = urlparse(DATASPHERE_URL).hostname.split(".")[0]  # pyright: ignore[reportOptionalMemberAccess]
SSO_URL: str = (
    f"https://{SUBDOMAIN}.authentication.eu10.hana.ondemand.com/saml/SSO/"
    f"alias/{SUBDOMAIN}.aws-live-eu10"
)
AUTH_URL: str = f"https://{SUBDOMAIN}.authentication.eu10.hana.ondemand.com"


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
                "Priority": "u=1, i",
                "X-Csrf-Token": "Fetch",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        # Load cookies if file exists
        if os.path.isfile(COOKIES_FILE):
            logger.info("Loading cookies from previous session...")
            with open(COOKIES_FILE) as cookie_file:
                # Load cookies from file
                try:
                    cookies = json.load(cookie_file)
                except json.decoder.JSONDecodeError:
                    logger.critical("Unknown error. Deleting cookies...")
                    if os.path.isfile(COOKIES_FILE):
                        os.remove(COOKIES_FILE)
                    logger.error("Please restart the program.")
                    sys.exit(1)

                # Load cookies into session
                for cookie in cookies:
                    self.session.cookies.set(
                        name=cookie["name"],
                        value=cookie["value"],
                        domain=cookie["domain"],
                        path=cookie["path"],
                    )

            # Check if cookie session is still active (expires after 1 hour)
            response = await self.session.get(
                url=f"{DATASPHERE_URL}/sap/fpa/services/rest/epm/session",
                params={"action": "logon"},
            )

            # If cookies expired
            if response.headers.get("X-Csrf-Token") is None:
                logger.debug(
                    "Datasphere session has expired. Starting new session..."
                )

            # Otherwise set headers and finish initialization
            else:
                self.session.headers.update(
                    {
                        "Accept-Language": "de",
                        "Origin": DATASPHERE_URL,
                        "X-Csrf-Token": response.headers["X-Csrf-Token"],
                    }
                )
                return self.session

        # If no cookies were found
        else:
            logger.debug("No cookies found.")

        # Start authentication/refresh
        await self._refresh_session()

        # Check if login was successful
        self.session.headers.update(
            {
                "Accept": "text/plain, */*; q=0.01",
                "Accept-Language": "en",
                "Priority": "u=1, i",
                "X-Csrf-Token": "Fetch",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        response = await self.session.get(
            url=f"{DATASPHERE_URL}/sap/fpa/services/rest/epm/session",
            params={"action": "logon"},
        )

        # Restart browser and load cookies if login failed (cookies expired)
        if response.headers.get("X-Csrf-Token") is None:
            logger.critical("Unknown error. Deleting cookies...")
            if os.path.isfile(COOKIES_FILE):
                os.remove(COOKIES_FILE)
            logger.error("Please restart the program.")
            sys.exit(1)

        # Set headers
        logger.info("Login successful.")
        self.session.headers.update(
            {
                "Accept-Language": "de",
                "Origin": DATASPHERE_URL,
                "X-Csrf-Token": response.headers["X-Csrf-Token"],
            }
        )
        return self.session

    async def _start_login(
        self, response: httpx.Response
    ) -> tuple[bool, httpx.Response]:
        """
        Starts login via requests or browser depending on the current settings.

        Loads all cookies into the requests session after successful
        browser authentication.

        Returns:
            tuple[bool, httpx.Response]: Returns True for requests to indicate
                                         that the flow has to be continued to
                                         save the persistent auth cookies.
                                         Returns False for browser to stop the
                                         remaining _refresh_session() flow.
                                         Returns the last response for requests
                                         or the received input params for
                                         browser.
        """
        if AUTHENTICATION_METHOD.upper() == "REQUESTS":
            logger.debug("Starting Microsoft SSO login via requests...")
            response = await self._start_requests_authentication(response)
            return True, response

        elif AUTHENTICATION_METHOD.upper() == "BROWSER":
            if BROWSER_TO_USE.upper() == "PLAYWRIGHT":
                logger.debug("Starting login via Playwright...")
                await self._start_browser_login_playwright()
            else:
                logger.debug("Starting login via browser...")
                self._start_browser_authentication()
            with open(COOKIES_FILE) as cookie_file:
                cookies = json.load(cookie_file)
                for cookie in cookies:
                    self.session.cookies.set(
                        name=cookie["name"],
                        value=cookie["value"],
                        domain=cookie["domain"],
                        path=cookie["path"],
                    )
            return False, response

        else:
            logger.critical(
                "Invalid authentication method. Please check your settings."
            )
            sys.exit(1)

    async def _refresh_session(self) -> None:
        """
        Refreshes the Datasphere session using the persistent auth cookies.
        Saves the updated cookies.

        Automatically starts the full authentication flow if the
        auth cookies have expired or don't exist.
        """

        # Important: User-Agent has to be Edge, otherwise the flow would fail
        for header in ("Priority", "X-Csrf-Token", "X-Requested-With"):
            self.session.headers.pop(header)
        self.session.headers.update(
            {
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8,application/"
                    "signed-exchange;v=b3;q=0.7"
                ),
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

        # 1. Request: https://<subdomain>.eu10.hcs.cloud.sap/dwaas-core/index.html
        response = await self.session.get(
            url=f"{DATASPHERE_URL}/dwaas-core/index.html",
        )
        oauth_url_result = re.search(r'location="([^"]+)"', response.text)
        if not oauth_url_result:
            logger.critical("Error parsing OAuth URL.")
            sys.exit(1)
        oauth_url = oauth_url_result.group(1)

        signature_cookie_value_result = re.search(
            r"signature=([^;]+)", response.text
        )
        if not signature_cookie_value_result:
            logger.critical("Error parsing signature cookie.")
            sys.exit(1)
        signature_cookie_value = signature_cookie_value_result.group(1)

        # Set cookies that would otherwise be set via JavaScript
        # (important for redirect after successful authentication)
        datasphere_domain = urlparse(DATASPHERE_URL).hostname
        self.session.cookies.set(
            name="fragmentAfterLogin",
            value="#/home",
            domain=str(datasphere_domain),
            path="/",
        )
        self.session.cookies.set(
            name="locationAfterLogin",
            value="/dwaas-core/index.html",
            domain=str(datasphere_domain),
            path="/",
        )
        self.session.cookies.set(
            name="signature",
            value=signature_cookie_value,
            domain=str(datasphere_domain),
            path="/",
        )

        # 2. Request: https://<subdomain>.authentication.eu10.hana.ondemand.com/oauth/authorize
        # redirects to: https://<subdomain>.authentication.eu10.hana.ondemand.com/login
        self.session.headers.update(
            {
                "DNT": "1",
                "Referer": f"{DATASPHERE_URL}/",
                "Accept-Language": "de",
            }
        )
        response = await self.session.get(url=oauth_url)

        # Parse SAML link
        soup = BeautifulSoup(response.text, "html.parser")
        saml_url = f"{AUTH_URL}/" + soup.find("a")["href"]  # type: ignore

        # 4. Request: https://<subdomain>.authentication.eu10.hana.ondemand.com/saml/discovery
        # redirects to: https://<subdomain>.authentication.eu10.hana.ondemand.com/saml/login/alias/<subdomain>.aws-live-eu10
        # redirects to: https://login.microsoftonline.com/<tenant_id>/saml2
        self.session.headers.update({"Referer": f"{AUTH_URL}/login"})
        response = await self.session.get(url=saml_url)

        # Check if MFA confirmation is required and start login
        if "<title>Working...</title>" not in response.text:
            proceed, response = await self._start_login(response)

            # Return if browser login was performed
            if not proceed:
                return

        # Parse values
        soup = BeautifulSoup(response.text, "html.parser")
        saml_response = soup.find("input", attrs={"name": "SAMLResponse"})[  # type: ignore
            "value"
        ]
        relay_state = soup.find("input", attrs={"name": "RelayState"})["value"]  # type: ignore

        # 5. / 11. Request: https://<subdomain>.authentication.eu10.hana.ondemand.com/saml/SSO/alias/<subdomain>.aws-live-eu10
        # redirects to: https://<subdomain>.authentication.eu10.hana.ondemand.com/oauth/authorize
        # redirects to: https://<subdomain>.eu10.hcs.cloud.sap/sso/login/callback
        data = {"SAMLResponse": saml_response, "RelayState": relay_state}
        self.session.headers.update(
            {"Referer": "https://login.microsoftonline.com/"}
        )
        response = await self.session.post(url=SSO_URL, data=data)

        # Save cookies to file
        logger.info("Saving cookies...")
        with open(COOKIES_FILE, "w") as cookies_file:
            json.dump(
                [
                    {
                        "domain": cookie.domain,
                        "name": cookie.name,
                        "path": cookie.path,
                        "secure": cookie.secure,
                        "value": cookie.value,
                    }
                    for cookie in self.session.cookies.__dict__["jar"]
                ],
                cookies_file,
            )

        # Prepare headers for method calls
        for header in (
            "Connection",
            "Upgrade-Insecure-Requests",
            "DNT",
            "Referer",
        ):
            self.session.headers.pop(header)

    async def _start_requests_authentication(
        self, response: httpx.Response
    ) -> httpx.Response:
        """
        Starts the Microsoft SSO login via requests.
        Sends a code to the Microsoft authenticator app. Prompts the user to
        enter their username and password via the Rich console.

        Args:
            response (httpx.Response): Response of the last request (containing
                                       the configuration for MFA).

        Returns:
            httpx.Response: Response of the last request (auth processing
                            after successful MFA verification).
        """

        # Fetch Rich console
        console = get_console()
        console._highlight = False

        # Notify user (additional delay to read message)
        logger.debug("MFA confirmation required...\n\n")
        sleep(2)

        # Prompt to enter username and password via Rich console
        prompt = Prompt()
        console.print(
            "Please enter your email address to login via Microsoft SSO."
        )
        email = prompt.ask("\nEmail address").strip()
        console.print("\nPlease enter the password of your Microsoft account.")
        console.print(
            "Warning: The input is masked and won't be shown on the screen.",
            style="bold yellow",
        )
        password = prompt.ask("\nPassword", password=True)
        console.print("\nGenerating MFA code...")

        # Parse config
        config_data_result = re.search(r"\$Config=({.*?});", response.text)
        if not config_data_result:
            logger.critical("Error parsing OAuth config.")
            sys.exit(1)
        config_data = config_data_result.group(1)
        config_data = json.loads(config_data)
        correlation_id = config_data["correlationId"]

        # Parse URL
        credential_type_url_result = re.search(
            r'"urlGetCredentialType":"([^"]+)"', response.text
        )
        if not credential_type_url_result:
            logger.warning("Error parsing credential type URL.")
            logger.warning("Using fallback URL...")
            credential_type_url = (
                "https://login.microsoftonline.com/common/GetCredentialType"
                "?mkt=de-DE"
            )
        else:
            credential_type_url = credential_type_url_result.group(1)

        # 5. Request: https://login.microsoftonline.com/common/GetCredentialType?mkt=de-DE
        url = credential_type_url
        data = {
            "username": email,
            "isOtherIdpSupported": True,
            "checkPhones": False,
            "isRemoteNGCSupported": True,
            "isCookieBannerShown": False,
            "isFidoSupported": True,
            "originalRequest": config_data["sCtx"],
            "country": "DE",
            "forceotclogin": False,
            "isExternalFederationDisallowed": False,
            "isRemoteConnectSupported": False,
            "federationFlags": 0,
            "isSignup": False,
            "flowToken": config_data["sFT"],
            "isAccessPassSupported": True,
            "isQrCodePinSupported": True,
        }
        self.session.headers.update(
            {
                "hpgid": str(config_data["hpgid"]),
                "hpgact": str(config_data["hpgact"]),
                "canary": config_data["apiCanary"],
                "client-request-id": correlation_id,
                "Accept": "application/json",
                "hpgrequestid": config_data["sessionId"],
                "DNT": "1",
                "Origin": "https://login.microsoftonline.com",
                "Referer": str(response.url),
            }
        )
        response = await self.session.post(url=url, json=data)
        flow_token = response.json()["FlowToken"]

        # Remove headers again
        for header in (
            "hpgid",
            "hpgact",
            "canary",
            "client-request-id",
            "hpgrequestid",
        ):
            self.session.headers.pop(header)

        # 6. Request: https://login.microsoftonline.com/<tenant_id>/login
        login_url = config_data["urlPost"]
        i19 = randint(12000, 20000)
        data = {
            "i13": 0,
            "login": email,
            "loginfmt": email,
            "type": 11,
            "LoginOptions": 3,
            "lrt": "",
            "lrtPartition": "",
            "hisRegion": "",
            "hisScaleUnit": "",
            "passwd": password,
            "ps": 2,
            "psRNGCDefaultType": "",
            "psRNGCEntropy": "",
            "psRNGCSLK": "",
            "canary": config_data["canary"],
            "ctx": config_data["sCtx"],
            "hpgrequestid": config_data["sessionId"],
            "flowToken": flow_token,
            "PPSX": "",
            "NewUser": 1,
            "FoundMSAs": "",
            "fspost": 0,
            "i21": 0,
            "CookieDisclosure": 0,
            "IsFidoSupported": 1,
            "isSignupPost": 0,
            "DfpArtifact": "",
            "i19": i19,
        }
        self.session.headers.update(
            {
                "Origin": "https://login.microsoftonline.com",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.7"
                ),
            }
        )
        response = await self.session.post(url=login_url, data=data)

        # Parse new config
        config_data_result = re.search(r"\$Config=({.*?});", response.text)
        if not config_data_result:
            logger.critical("Error parsing OAuth config.")
            sys.exit(1)
        config_data = config_data_result.group(1)
        config_data = json.loads(config_data)

        # 7. Request: https://login.microsoftonline.com/common/SAS/BeginAuth
        begin_auth_url = (
            "https://login.microsoftonline.com/common/SAS/BeginAuth"
        )
        data = {
            "AuthMethodId": "PhoneAppNotification",
            "Method": "BeginAuth",
            "ctx": config_data["sCtx"],
            "flowToken": config_data["sFT"],
        }
        self.session.headers.update(
            {
                "hpgid": str(config_data["hpgid"]),
                "hpgact": str(config_data["hpgact"]),
                "canary": config_data["apiCanary"],
                "client-request-id": config_data["correlationId"],
                "Accept": "application/json",
                "hpgrequestid": config_data["sessionId"],
                "Origin": "https://login.microsoftonline.com",
                "Referer": str(response.url),
            }
        )
        response = await self.session.post(url=begin_auth_url, json=data)
        auth_data = response.json()

        # Display authenticator code
        if str(auth_data["Entropy"]) == 0:
            console.print(
                "Unknown error. Please restart...",
                style="bold red",
            )
            sys.exit()
        entropy = auth_data["Entropy"]
        console.print(f"Authenticator Code: {entropy}", style="bold green")

        # 8. Request: https://login.microsoftonline.com/common/SAS/EndAuth
        end_auth_url = "https://login.microsoftonline.com/common/SAS/EndAuth"
        poll_count = 1
        params = {
            "authMethodId": "PhoneAppNotification",
            "pollCount": poll_count,
        }
        self.session.headers.update(
            {
                "x-ms-flowToken": auth_data["FlowToken"],
                "x-ms-ctx": auth_data["Ctx"],
                "client-request-id": auth_data["CorrelationId"],
                "x-ms-sessionId": auth_data["SessionId"],
            }
        )

        # 9. Request (and further requests) to check MFA status
        console.print("\nWaiting for confirmation...")
        last_poll_start_time = None
        last_poll_end_time = None
        flow_token = None
        ctx = None
        while True:
            last_poll_start_time = round(time() * 1000)
            response = await self.session.get(url=end_auth_url, params=params)
            challenge_data = response.json()
            last_poll_end_time = round(time() * 1000)
            if challenge_data["ResultValue"] != "AuthenticationPending":
                flow_token = challenge_data["FlowToken"]
                ctx = challenge_data["Ctx"]
                break
            params["lastPollStart"] = last_poll_start_time
            params["lastPollEnd"] = last_poll_end_time
            sleep(1)
        console.print("Received confirmation.\n\n", style="bold green")

        # 10. Request: https://login.microsoftonline.com/common/SAS/ProcessAuth
        process_auth_url = (
            "https://login.microsoftonline.com/common/SAS/ProcessAuth"
        )
        data = {
            "type": 22,
            "request": ctx,
            "mfaLastPollStart": last_poll_start_time,
            "mfaLastPollEnd": last_poll_end_time,
            "mfaAuthMethod": "PhoneAppNotification",
            "login": email,
            "flowToken": flow_token,
            "hpgrequestid": response.headers["x-ms-request-id"],
            "sacxt": "",
            "hideSmsInMfaProofs": False,
            "canary": config_data["canary"],
            "i19": i19 + randint(500, 1000),
        }
        for headers in (
            "hpgid",
            "hpgact",
            "canary",
            "client-request-id",
            "hpgrequestid",
            "x-ms-flowToken",
            "x-ms-ctx",
            "x-ms-sessionId",
        ):
            self.session.headers.pop(headers)
        self.session.headers.update(
            {
                "Origin": "https://login.microsoftonline.com",
                "Upgrade-Insecure-Requests": "1",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.7"
                ),
            }
        )
        response = await self.session.post(url=process_auth_url, data=data)
        self.session.headers.pop("Origin")
        return response

    def _start_browser_authentication(self) -> None:
        """
        Configures the Selenium browser for manual login.
        Loads cookies from the browser and closes it.
        """

        # TODO: Edge noch testen!

        # Event listener to save all cookies (since get_cookies()
        # only retrieves cookies of the current page when called)
        class CookieListener(AbstractEventListener):
            def __init__(self):
                self.all_cookies = []

            def after_navigate_to(self, _, driver):
                """
                Called after each navigation (redirect).
                BUT: The cookies of the loaded page have to be
                saved explicitly.

                Args:
                    _ (Any): Unused arguments.
                    driver (WebDriver): WebDriver to add listener to.
                """
                self.all_cookies.extend(driver.get_cookies())

        # Configure WebDriver settings
        options = BROWSER_MAPPING[BROWSER_TO_USE]["options"]()
        options.add_argument("--log-level=CRITICAL")
        options.add_argument("start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        # Create/set path for browser profile
        browser_data_path = DATA_DIR / f".{BROWSER_TO_USE.lower()}"
        if not os.path.exists(browser_data_path):
            os.mkdir(browser_data_path)
        options.add_argument(f"user-data-dir={browser_data_path}")

        # Initialize WebDriver and WebDriverWait
        with BROWSER_MAPPING[BROWSER_TO_USE]["driver"](
            options=options
        ) as driver:
            # Initialize CookieListener and EventFiringWebDriver
            listener = CookieListener()
            ef_driver = EventFiringWebDriver(driver, listener)

            # Initialize wait
            wait = WebDriverWait(
                ef_driver,  # pyright: ignore[reportArgumentType]
                timeout=300,
            )

            # Load homepage
            logger.debug(
                "Loading Datasphere homepage in browser. "
                "Please log in manually..."
            )
            ef_driver.get(url=DATASPHERE_URL)
            wait.until(
                EC.text_to_be_present_in_element(
                    (By.ID, "__title0"), "SAP Datasphere"
                )
            )
            listener.all_cookies.extend(
                ef_driver.get_cookies()
            )  # IMPORTANT: to add Datasphere cookies
            sleep(5)

            # IMPORTANT: to obtain persistent Microsoft auth cookies
            logger.debug("Loading Microsoft login...")
            ef_driver.get(url="https://login.microsoftonline.com")
            sleep(5)  # for additional safety

            # Save cookies
            logger.info("Saving cookies...")
            with open(COOKIES_FILE, "w") as cookie_file:
                json.dump(
                    listener.all_cookies,
                    cookie_file,
                    indent=4,
                    ensure_ascii=True,
                )

            # Close EventFiringWebDriver
            ef_driver.quit()

    async def _start_browser_login_playwright(self) -> None:
        """
        Configures the Playwright browser for manual login.
        Loads cookies from the browser and closes it.

        Automatically saves all cookies received during the session.
        """

        # Create/set path for browser profile
        browser_data_path = DATA_DIR / f".{BROWSER_TO_USE.lower()}"
        if not os.path.exists(browser_data_path):
            os.mkdir(browser_data_path)

        # Start Playwright browser
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch_persistent_context(
                user_data_dir=browser_data_path,
                headless=False,
                args=["--start-maximized"],
                no_viewport=True,
            )
            page = await browser.new_page()

            # Open page and wait for login
            logger.debug(
                "Loading Datasphere homepage in browser. "
                "Please log in manually..."
            )
            await page.goto(DATASPHERE_URL)
            await page.wait_for_selector(
                "#__title0", timeout=300000
            )  # 5 minute timeout

            # Quick wait time for additional safety
            await asyncio.sleep(3)

            # Fetch all cookies
            all_cookies = await browser.cookies()
            logger.info("Saving cookies...")
            with open(COOKIES_FILE, "w", encoding="utf-8") as cookie_file:
                json.dump(
                    all_cookies, cookie_file, indent=4, ensure_ascii=True
                )

            # Close browser
            await browser.close()

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
