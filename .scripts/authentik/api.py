#!/usr/bin/env python3
"""Talk to the local Authentik API for the theme preview.

The shell scripts in this directory are the entry points. This file publishes
authentik/style.css onto the default brand and walks the login flow. It reads
authentik/.env and does not print the password or API token.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# .scripts/authentik/api.py -> repository root
ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / "authentik" / ".env"
CSS_PATH = ROOT / "authentik" / "style.css"
DEFAULT_BASE = "http://127.0.0.1:9000"

# Present in authentik/style.css. Used to refuse the wrong file and to confirm
# the public brand payload actually contains this theme.
THEME_MARKER = "--abyss-accent"
USER_AGENT = "platform-themes-authentik"


class AuthentikError(RuntimeError):
    """Expected failure while waiting for, updating, or signing in to Authentik."""


def load_env(path: Path) -> dict[str, str]:
    """Read the generated dotenv file. Values are not written to stdout."""
    if not path.is_file():
        raise AuthentikError(
            f"Missing {path}. Run .scripts/authentik/up.sh to generate local credentials."
        )

    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
    return env


def require(env: dict[str, str], key: str) -> str:
    value = env.get(key, "")
    if not value or value == "change-me":
        raise AuthentikError(f"{ENV_PATH} is missing a generated {key}.")
    return value


class Client:
    """Small JSON client. A bearer token is used for admin calls; the login flow uses cookies."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        token: bool = True,
        attempts: int = 1,
        timeout: int = 60,
    ) -> object:
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {self.token}"

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    raw = response.read().decode()
                    if not raw:
                        return {}
                    return json.loads(raw)
            except urllib.error.HTTPError as error:
                detail = error.read().decode(errors="replace")[:800]
                last_error = AuthentikError(
                    f"{method} {path} failed with HTTP {error.code}: {detail}"
                )
                # Startup races (brand not created, worker still migrating) are worth retrying.
                if error.code not in {401, 404, 409, 500, 502, 503, 504} or attempt == attempts:
                    raise last_error
            except urllib.error.URLError as error:
                last_error = AuthentikError(f"{method} {path} failed: {error.reason}")
                if attempt == attempts:
                    raise last_error
            time.sleep(min(3 * attempt, 10))

        raise AuthentikError(str(last_error))


def results_of(payload: object) -> list[dict]:
    """Accept either a paginated object or a bare list."""
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise AuthentikError("Unexpected Authentik list payload.")


def wait_until_ready(client: Client, timeout_seconds: int) -> None:
    """Block until the default brand exists.

    /-/health/ready/ turns 200 while blueprints are still applying, so an empty
    brand list is treated as "not ready yet".
    """
    deadline = time.time() + timeout_seconds
    last_error = "Authentik did not become ready."
    while time.time() < deadline:
        try:
            request = urllib.request.Request(
                f"{client.base}/-/health/ready/",
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise AuthentikError(f"health returned HTTP {response.status}")

            brands = client.request(
                "GET",
                "/api/v3/core/brands/?page_size=1",
                attempts=1,
                timeout=20,
            )
            if not results_of(brands):
                raise AuthentikError("default brand is not created yet")

            print(f"Authentik API is ready at {client.base}")
            return
        except Exception as error:
            last_error = str(error)
            time.sleep(3)

    raise AuthentikError(last_error)


def default_brand(client: Client) -> dict:
    payload = client.request("GET", "/api/v3/core/brands/?page_size=100", attempts=5)
    brands = results_of(payload)
    if not brands:
        raise AuthentikError("Authentik has no brands yet.")
    for brand in brands:
        if brand.get("default") is True:
            return brand
    return brands[0]


def apply_css(client: Client, css_path: Path) -> None:
    """Write the theme onto the default brand and read it back without auth."""
    css = css_path.read_text()
    if THEME_MARKER not in css:
        raise AuthentikError(
            f"{css_path} does not contain {THEME_MARKER}; refusing to publish an unexpected file."
        )

    brand = default_brand(client)
    brand_uuid = brand.get("brand_uuid")
    if not brand_uuid:
        raise AuthentikError("Default brand response did not include brand_uuid.")

    updated = client.request(
        "PATCH",
        f"/api/v3/core/brands/{brand_uuid}/",
        {"branding_custom_css": css},
        attempts=3,
    )
    if not isinstance(updated, dict):
        raise AuthentikError("Brand update returned an unexpected payload.")

    # The login page loads this unauthenticated endpoint, so it is the check that matters.
    current = client.request("GET", "/api/v3/core/brands/current/", token=False, attempts=3)
    if not isinstance(current, dict):
        raise AuthentikError("Current brand lookup returned an unexpected payload.")

    published = current.get("branding_custom_css") or ""
    if not isinstance(published, str) or THEME_MARKER not in published:
        raise AuthentikError("Public brand CSS does not contain the theme after update.")

    digest = hashlib.sha256(css.encode()).hexdigest()[:12]
    print(
        f"Published {css_path.relative_to(ROOT)} to brand {brand_uuid} "
        f"({len(css)} bytes, sha256 {digest})."
    )
    print("Public /api/v3/core/brands/current/ includes the theme.")


def authentication_flow_slug(client: Client) -> str:
    payload = client.request(
        "GET",
        "/api/v3/flows/instances/?designation=authentication&page_size=50",
        attempts=3,
    )
    slugs = [str(flow.get("slug")) for flow in results_of(payload) if flow.get("slug")]
    if "default-authentication-flow" in slugs:
        return "default-authentication-flow"
    if slugs:
        return slugs[0]
    return "default-authentication-flow"


def login(client: Client, username: str, password: str) -> None:
    """Walk the flow executor until Authentik redirects the signed-in user.

    The default flow asks for a username, then a password, then completes a
    user-login stage. Each response names the current stage in `component`.
    """
    slug = authentication_flow_slug(client)
    path = f"/api/v3/flows/executor/{slug}/"
    payload = client.request("GET", path, token=False, attempts=5)

    for _ in range(8):
        if not isinstance(payload, dict):
            raise AuthentikError("Authentication flow returned a non-object response.")

        component = str(payload.get("component") or "")
        if component in {"xak-flow-redirect", "ak-stage-flow-redirect"}:
            print(f"Logged in as {username} through {slug}.")
            return
        if payload.get("response_errors"):
            raise AuthentikError(
                f"Authentication flow rejected the attempt at {component or 'unknown stage'}."
            )

        if component == "ak-stage-identification":
            body: dict[str, str] = {"uid_field": username}
        elif component == "ak-stage-password":
            body = {"password": password}
        elif component in {"ak-stage-user-login", "ak-stage-prompt"}:
            body = {}
        else:
            raise AuthentikError(f"Unsupported authentication stage {component or 'unknown'}.")

        payload = client.request("POST", path, body, token=False, attempts=3)

    raise AuthentikError("Authentication flow did not finish.")


def build_client(base: str) -> Client:
    env = load_env(ENV_PATH)
    return Client(
        base or env.get("AUTHENTIK_URL", DEFAULT_BASE),
        require(env, "AUTHENTIK_BOOTSTRAP_TOKEN"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="")
    subcommands = parser.add_subparsers(dest="command", required=True)

    wait = subcommands.add_parser("wait", help="block until the default brand exists")
    wait.add_argument("--timeout", type=int, default=180)
    subcommands.add_parser("apply", help="publish authentik/style.css onto the default brand")
    subcommands.add_parser("login", help="sign in as akadmin through the authentication flow")
    subcommands.add_parser("deploy", help="publish the theme, then sign in")
    args = parser.parse_args()

    try:
        client = build_client(args.base_url)
        if args.command == "wait":
            wait_until_ready(client, args.timeout)
        elif args.command == "apply":
            apply_css(client, CSS_PATH)
        elif args.command == "login":
            env = load_env(ENV_PATH)
            login(client, "akadmin", require(env, "AUTHENTIK_BOOTSTRAP_PASSWORD"))
        elif args.command == "deploy":
            apply_css(client, CSS_PATH)
            env = load_env(ENV_PATH)
            login(client, "akadmin", require(env, "AUTHENTIK_BOOTSTRAP_PASSWORD"))
        else:
            raise AuthentikError(f"Unknown command {args.command}.")
    except (AuthentikError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
