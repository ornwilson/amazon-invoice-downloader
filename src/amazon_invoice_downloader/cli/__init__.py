# SPDX-FileCopyrightText: 2023-present David C Wang <dcwangmit01@gmail.com>
#
# SPDX-License-Identifier: MIT

"""
Amazon Invoice Downloader

Usage:
  amazon-invoice-downloader.py \
    [--email=<email> --password=<password>] \
    [--year=<YYYY> | --date-range=<YYYYMMDD-YYYYMMDD>] \
    [--filename-format=<format>]
  amazon-invoice-downloader.py (-h | --help)
  amazon-invoice-downloader.py (-v | --version)

Login Options:
  --email=<email>          Amazon login email  [default: $AMAZON_EMAIL].
  --password=<password>    Amazon login password  [default: $AMAZON_PASSWORD].

Date Range Options:
  --date-range=<YYYYMMDD-YYYYMMDD>  Start and end date range
  --year=<YYYY>                     Year, formatted as YYYY  [default: <CUR_YEAR>].

Output Options:
  --filename-format=<format>  Filename template for each downloaded invoice, using
                              named placeholders {date} (YYYYMMDD), {total} (e.g. 12.34),
                              and {orderid}. At least one placeholder is required, and
                              ".pdf" is appended automatically.
                              [default: {date}_{total}_amazon_{orderid}]

Options:
  -h --help                Show this screen.
  -v --version             Show version.

Examples:
  amazon-invoice-downloader.py --year=2022  # Uses .env file or env vars $AMAZON_EMAIL and $AMAZON_PASSWORD
  amazon-invoice-downloader.py --date-range=20220101-20221231
  amazon-invoice-downloader.py --email=user@example.com --password=secret  # Defaults to current year
  amazon-invoice-downloader.py --email=user@example.com --password=secret --year=2022
  amazon-invoice-downloader.py --email=user@example.com --password=secret --date-range=20220101-20221231
  amazon-invoice-downloader.py --filename-format="{date}_{orderid}"
  amazon-invoice-downloader.py --email=user@example.com --password=secret --date-range=20220101-20221231 --filename-format="{date}_Amazon_{orderid}_{total}"
  amazon-invoice-downloader --date-range=20241224-20241231 --filename-format="{date}_Amazon_{orderid}_{total}"

Features:
  - Remote debugging enabled on port 9222 for AI MCP Servers
  - Virtual authenticator configured to prevent passkey dialogs
  - Stealth mode enabled to avoid detection

Credential Precedence:
  1. Command line arguments (--email, --password)
  2. Environment variables ($AMAZON_EMAIL, $AMAZON_PASSWORD)
  3. .env file (automatically loaded if env vars not set)
"""

import os
import random
import string
import sys
import time
from datetime import datetime
from pathlib import Path

from docopt import docopt
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError, sync_playwright
from playwright_stealth import Stealth

from ..__about__ import __version__

DEFAULT_FILENAME_FORMAT = "{date}_{total}_amazon_{orderid}"
VALID_PLACEHOLDERS = ("date", "total", "orderid")

# Characters that Windows (and, for safety, other OSes) forbid in filenames.
_RESERVED_FILENAME_CHARS = '<>:"|?*'

# Representative values used to render a sample filename during validation.
_SAMPLE_PLACEHOLDER_VALUES = {"date": "20240101", "total": "12.34", "orderid": "123-4567890-1234567"}


def validate_filename_format(filename_format):
    """Validate a --filename-format template and return its normalized form.

    Raises ValueError with a human-readable message describing the problem.
    """
    filename_format = filename_format.strip()
    if not filename_format:
        raise ValueError("--filename-format must not be empty")

    placeholder_list = ", ".join("{" + name + "}" for name in VALID_PLACEHOLDERS)

    try:
        parsed_fields = list(string.Formatter().parse(filename_format))
    except ValueError as e:
        raise ValueError(f"{filename_format!r} is not a valid template: {e}") from e

    field_names = [field_name for _, field_name, _, _ in parsed_fields if field_name is not None]

    if not field_names:
        raise ValueError(
            f"{filename_format!r} must contain at least one placeholder ({placeholder_list}); "
            "otherwise every order would be saved to the same file"
        )

    for name in field_names:
        if name == "" or name.isdigit():
            raise ValueError(
                f"{filename_format!r} uses a positional placeholder; "
                f"use named placeholders instead: {placeholder_list}"
            )
        if name not in VALID_PLACEHOLDERS:
            raise ValueError(
                f"unknown placeholder {{{name}}} in {filename_format!r}; valid placeholders are {placeholder_list}"
            )

    rendered = filename_format.format(**_SAMPLE_PLACEHOLDER_VALUES)

    if "/" in rendered or "\\" in rendered:
        raise ValueError(f"{filename_format!r} contains a path separator; it must produce a single filename")

    bad_chars = sorted(set(rendered) & set(_RESERVED_FILENAME_CHARS))
    if bad_chars:
        raise ValueError(
            f"{filename_format!r} produces filenames containing characters that cannot be used in a filename: "
            f"{' '.join(bad_chars)}"
        )
    if any(ord(c) < 32 for c in rendered):
        raise ValueError(f"{filename_format!r} produces filenames containing control characters")

    if "orderid" not in field_names:
        print(
            f"⚠️ Warning: --filename-format {filename_format!r} does not include {{orderid}}; "
            "orders with the same date and total may overwrite each other",
            file=sys.stderr,
        )

    return filename_format


def load_env_if_needed():
    """Load environment variables from .env file if it exists and variables aren't set."""
    # Check if Amazon credentials are already set in environment
    amazon_email = os.environ.get('AMAZON_EMAIL')
    amazon_password = os.environ.get('AMAZON_PASSWORD')

    # If both are already set, no need to load .env
    if amazon_email and amazon_password:
        return

    # Look for .env file in current directory and parent directories
    current_dir = Path.cwd()
    env_file = None

    # Check current directory and up to 3 parent directories
    for i in range(4):
        check_path = current_dir / '.env'
        if check_path.exists():
            env_file = check_path
            break
        current_dir = current_dir.parent

    if env_file:
        print(f"Loading environment variables from {env_file}")
        load_dotenv(env_file)
    else:
        print("No .env file found in current directory or parent directories")


def sleep():
    # Add human latency
    # Generate a random sleep time between 2 and 5 seconds
    sleep_time = random.uniform(2, 5)
    # Sleep for the generated time
    time.sleep(sleep_time)


def run(playwright, args):
    filename_format = args.get("--filename-format") or DEFAULT_FILENAME_FORMAT

    email = args.get("--email")
    if email == "$AMAZON_EMAIL":
        email = os.environ.get("AMAZON_EMAIL")

    password = args.get("--password")
    if password == "$AMAZON_PASSWORD":
        password = os.environ.get("AMAZON_PASSWORD")

    # Parse date ranges int start_date and end_date
    if args["--date-range"]:
        start_date, end_date = args["--date-range"].split("-")
    elif args["--year"] != "<CUR_YEAR>":
        start_date, end_date = args["--year"] + "0101", args["--year"] + "1231"
    else:
        year = str(datetime.now().year)
        start_date, end_date = year + "0101", year + "1231"
    start_date = datetime.strptime(start_date, "%Y%m%d")
    end_date = datetime.strptime(end_date, "%Y%m%d")

    # Ensure the location exists for where we will save our downloads
    target_dir = os.getcwd() + "/" + "downloads"
    os.makedirs(target_dir, exist_ok=True)

    # Create Playwright context with Chromium
    # Always use CDP for virtual authenticator and remote debugging
    print("🚀 Launching Chromium with CDP debugging on port 9222")
    print("📱 You can connect to this browser at: http://localhost:9222")
    print("🔗 AI assistant can control this browser instance via CDP")

    # Launch browser with CDP endpoint
    browser = playwright.chromium.launch(
        headless=False,
        args=[
            '--remote-debugging-port=9222',
            '--remote-debugging-address=0.0.0.0',
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
        ],
    )

    # Connect to the browser using CDP
    browser = playwright.chromium.connect_over_cdp("http://localhost:9222")

    # Create context and page
    context = browser.new_context()
    page = context.new_page()

    # Set up virtual authenticator to prevent passkey dialogs
    print("🔐 Setting up virtual authenticator to disable passkeys")
    try:
        client = page.context.new_cdp_session(page)
        client.send("WebAuthn.enable")
        client.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }
            },
        )
        print("✅ Virtual authenticator configured successfully")
    except Exception as e:
        print(f"⚠️ Warning: Could not configure virtual authenticator: {e}")

    Stealth().apply_stealth_sync(page)

    # Wait for page to fully load. "domcontentloaded" alone isn't enough here:
    # Amazon's AWS WAF bot-check interstitial fires its own JS reload/redirect
    # shortly *after* domcontentloaded, so querying immediately can race an
    # in-flight navigation and raise "Execution context was destroyed".
    # wait_for_selector below (rather than an immediate query_selector) rides
    # out that settle time instead of racing it.
    page.goto("https://amazon.com/")
    page.wait_for_load_state("load")

    # Amazon sometimes serves a bot-check interstitial ("Click the button
    # below to continue shopping") before the real homepage. Click through
    # it if present, since nothing else on that page matches our selectors.
    continue_shopping = page.query_selector('button:has-text("Continue shopping")')
    if continue_shopping:
        print("Bot-check interstitial detected, clicking through...")
        continue_shopping.click()
        page.wait_for_load_state("load")
        sleep()

    # Check if we're on the less fully featured page. Use wait_for_selector
    # (with a real timeout) instead of an instant query_selector so we wait
    # out any trailing redirect/reload rather than racing it.
    try:
        page.wait_for_selector(
            'a:has-text("Returns & Orders"), a:has-text("Your Account")',
            timeout=15000,
        )
    except Exception:
        pass  # handled by the None checks below, which capture diagnostics

    test_less_featured_page = page.query_selector('a:has-text("Returns & Orders")')
    if not test_less_featured_page:
        print("Less featured page detected, navigating to sign-in...")
        your_account_link = page.query_selector('a:has-text("Your Account")')
        if not your_account_link:
            try:
                debug_html = os.path.join(target_dir, "debug_unrecognized_page.html")
                debug_png = os.path.join(target_dir, "debug_unrecognized_page.png")
                with open(debug_html, "w", encoding="utf-8") as f:
                    f.write(page.content())
                page.screenshot(path=debug_png)
                link_texts = [
                    a.inner_text().strip()
                    for a in page.query_selector_all("a")
                    if a.inner_text().strip()
                ]
                diagnostics = (
                    f"URL was: {page.url}\n"
                    f"Visible link texts: {link_texts}\n"
                    f"Saved page HTML to {debug_html} and screenshot to {debug_png}."
                )
            except Exception as diag_error:
                diagnostics = (
                    f"Additionally failed to capture diagnostics (page was "
                    f"still navigating): {diag_error}"
                )
            raise RuntimeError(
                "Could not find 'Returns & Orders' or 'Your Account' link. "
                + diagnostics
            )
        your_account_link.click()
        page.wait_for_load_state("load")
        sleep()

    # Locator.click() (unlike query_selector) auto-waits and retries against
    # actionability, so it survives the trailing redirect/reload that keeps
    # breaking the one-shot query_selector(...).click() pattern above.
    try:
        page.get_by_role("link", name="Hello, sign in").click(timeout=10000)
    except TimeoutError:
        # Nav didn't render (bot-detection stub or layout change); navigate directly to sign-in
        page.goto("https://www.amazon.com/gp/sign-in.html")
    page.wait_for_load_state("domcontentloaded")
    sleep()

    if email:
        page.get_by_label("Email").fill(email)
        page.get_by_role("button", name="Continue").click()
        page.wait_for_load_state("domcontentloaded")
        sleep()

    if password:
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_load_state("domcontentloaded")
        sleep()

    # Check for 2FA page
    if page.query_selector('title:has-text("Two-Step Verification")'):
        print("🔐 2FA detected - please complete authentication in browser")
        while page.query_selector('title:has-text("Two-Step Verification")'):
            time.sleep(1)
        print("✅ 2FA completed")
    page.wait_for_load_state("domcontentloaded")

    sleep()
    page.wait_for_selector("a >> text=Returns & Orders", timeout=0).click()
    sleep()

    # Get a list of years from the select options
    select = page.wait_for_selector("select#time-filter")
    years = select.inner_text().split("\n")  # skip the first two text options

    # Filter years to include only numerical years (YYYY)
    years = [year for year in years if year.isnumeric()]

    # Filter years to the include only the years between start_date and end_date inclusively
    years = [year for year in years if start_date.year <= int(year) <= end_date.year]
    years.sort(reverse=True)

    # Year Loop (Run backwards through the time range from years to pages to orders)
    for year in years:
        # Select the year in the order filter
        page.select_option('form[action="/your-orders/orders"] select#time-filter', value=f"year-{year}")
        sleep()

        # Page Loop
        first_page = True
        done = False
        while not done:
            # Go to the next page pagination, and continue downloading
            #   if there is not a next page then break
            try:
                if first_page:
                    first_page = False
                else:
                    page.get_by_role("link", name="Next →").click()
                sleep()  # sleep after every page load
            except TimeoutError:
                # There are no more pages
                break

            # Order Loop
            order_cards = page.query_selector_all(".order-card.js-order-card")
            for order_card in order_cards:
                # Parse the order card to create the date and file_name
                spans = order_card.query_selector_all("span")
                # Debug:
                # for i,s in enumerate(spans): print(i, s.inner_text())
                # print(f"span count: {len(spans)}")
                # for i, s in enumerate(spans):
                #     try:
                #         print(f"span[{i}] = {s.inner_text().strip()!r}")
                #     except Exception as e:
                #         print(f"span[{i}] = <error reading text: {e}>")

                # if len(spans) <= 4:
                #     print("Order card HTML:")
                #     print(order_card.inner_html())
                #     raise RuntimeError("Order card had fewer than 5 spans")

                if spans[4].inner_text().strip().lower() == "cancelled":
                    continue

                date = datetime.strptime(spans[1].inner_text(), "%B %d, %Y")
                total = spans[3].inner_text().replace("$", "").replace(",", "")  # remove dollar sign and commas
                # Scoped to order_card, not page: page.query_selector(".yohtmlc-order-id")
                # would return the first match on the whole page, assigning every
                # order on the page the same (first) order id.
                order_id_parent = order_card.query_selector(".yohtmlc-order-id")
                order_id_span = order_id_parent.query_selector("span.a-color-secondary:not(.a-text-caps)")
                orderid = order_id_span.inner_text()
                date_str = date.strftime("%Y%m%d")
                file_name = f"{target_dir}/{filename_format.format(date=date_str, total=total, orderid=orderid)}.pdf"

                if date > end_date:
                    continue
                elif date < start_date:
                    done = True
                    break

                if os.path.isfile(file_name):
                    print(f"File [{file_name}] already exists")
                else:
                    # Not every order card has a "View invoice" link (e.g. older
                    # or digital orders) - skip it rather than aborting the
                    # whole run on one order.
                    invoice_link_el = order_card.query_selector(
                        'xpath=//a[contains(text(), "View invoice")]'
                    )
                    if not invoice_link_el:
                        link_texts = [
                            a.inner_text().strip()
                            for a in order_card.query_selector_all("a")
                            if a.inner_text().strip()
                        ]
                        print(
                            f"⚠️ Warning: No 'View invoice' link for order [{orderid}] "
                            f"dated [{date_str}]; skipping. Links on this card: {link_texts}"
                        )
                        continue

                    print(f"Saving file [{file_name}]")
                    # Save
                    link = "https://www.amazon.com/" + invoice_link_el.get_attribute("href")
                    invoice_page = context.new_page()
                    invoice_page.goto(link)
                    invoice_page.pdf(
                        path=file_name,
                        format="Letter",
                        margin={"top": ".5in", "right": ".5in", "bottom": ".5in", "left": ".5in"},
                    )
                    invoice_page.close()

    # Close the browser
    context.close()
    browser.close()


def amazon_invoice_downloader():
    # Load environment variables from .env file if needed
    load_env_if_needed()

    args = docopt(__doc__)
    # print(args)
    if args['--version']:
        print(__version__)
        sys.exit(0)

    try:
        validate_filename_format(args.get("--filename-format") or DEFAULT_FILENAME_FORMAT)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    with sync_playwright() as playwright:
        run(playwright, args)
