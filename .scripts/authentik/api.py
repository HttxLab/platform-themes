#!/usr/bin/env python3
"""Talk to the local Authentik API for the theme preview.

The shell scripts in this directory are the entry points. This file publishes
authentik/style.css onto the default brand, enables the login widgets the theme
styles, and walks the login flow. It reads authentik/.env and does not print
the password, API token, or TOTP secret.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.cookiejar
import json
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
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

# Stages the default blueprint already creates. configure() only fills in the
# widgets the theme actually styles.
IDENTIFICATION_STAGE_NAME = "default-authentication-identification"
MFA_STAGE_NAME = "default-authentication-mfa-validation"
USER_LOGIN_STAGE_NAME = "default-authentication-login"
CAPTCHA_STAGE_NAME = "theme-preview-turnstile"
PASSWORDLESS_FLOW_SLUG = "theme-preview-passwordless"
TOTP_DEVICE_NAME = "theme-preview"

# Cloudflare's published Turnstile test widget: visible, and it always emits
# TURNSTILE_DUMMY_TOKEN. The browser loads js_url. The Authentik container
# cannot reach the public internet here, so siteverify is the compose service
# captcha-verify, which accepts that token.
TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
TURNSTILE_TEST_SECRET = "1x0000000000000000000000000000000AA"
TURNSTILE_JS_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
TURNSTILE_VERIFY_URL = "http://captcha-verify:8080/siteverify"
TURNSTILE_DUMMY_TOKEN = "XXXX.DUMMY.TOKEN.XXXX"


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


def totp_code(secret_hex: str, at: float | None = None) -> str:
    """Return the current 6-digit code for a hex TOTP key.

    Authentik's default device is SHA1, 6 digits, and a 30-second step.
    """
    if len(secret_hex) != 40 or any(char not in "0123456789abcdefABCDEF" for char in secret_hex):
        raise AuthentikError(
            f"{ENV_PATH} AUTHENTIK_TOTP_SECRET must be 40 hex characters. "
            "Run .scripts/authentik/up.sh to generate it."
        )
    moment = time.time() if at is None else at
    counter = int(moment // 30)
    digest = hmac.new(bytes.fromhex(secret_hex), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def wait_for_fresh_totp_window() -> None:
    """Avoid submitting a code that expires before Authentik checks it."""
    remaining = 30 - (time.time() % 30)
    if remaining < 2:
        time.sleep(remaining + 0.4)


def stage_by_name(client: Client, collection: str, name: str) -> dict | None:
    query = urllib.parse.urlencode({"name": name, "page_size": 20})
    payload = client.request("GET", f"/api/v3/stages/{collection}/?{query}", attempts=3)
    for stage in results_of(payload):
        if stage.get("name") == name:
            return stage
    return None


def require_stage(client: Client, collection: str, name: str) -> dict:
    stage = stage_by_name(client, collection, name)
    if stage is None or not stage.get("pk"):
        raise AuthentikError(f"Authentik has no stage named {name}.")
    return stage


def ensure_turnstile_stage(client: Client) -> str:
    """Create or update the visible Turnstile test stage and return its pk."""
    body = {
        "name": CAPTCHA_STAGE_NAME,
        "public_key": TURNSTILE_SITE_KEY,
        "private_key": TURNSTILE_TEST_SECRET,
        "js_url": TURNSTILE_JS_URL,
        "api_url": TURNSTILE_VERIFY_URL,
        "interactive": True,
        "request_content_type": "application/x-www-form-urlencoded",
        # Turnstile does not use reCAPTCHA scores. -1 disables both bounds.
        "score_min_threshold": -1,
        "score_max_threshold": -1,
        "error_on_invalid_score": True,
    }
    existing = stage_by_name(client, "captcha", CAPTCHA_STAGE_NAME)
    if existing and existing.get("pk"):
        client.request(
            "PATCH",
            f"/api/v3/stages/captcha/{existing['pk']}/",
            body,
            attempts=3,
        )
        return str(existing["pk"])

    created = client.request("POST", "/api/v3/stages/captcha/", body, attempts=3)
    if isinstance(created, dict) and created.get("pk"):
        return str(created["pk"])
    created = require_stage(client, "captcha", CAPTCHA_STAGE_NAME)
    return str(created["pk"])


def ensure_passwordless_flow(client: Client, mfa_pk: str) -> str:
    """Create the flow behind the "Use a security key" button.

    That button is the identification stage's passwordless flow, not the
    passkey challenge. The flow opens the WebAuthn prompt, then the user-login
    stage. The username and password path does not go through it.
    """
    payload = client.request("GET", "/api/v3/flows/instances/?page_size=100", attempts=3)
    flow = next(
        (item for item in results_of(payload) if item.get("slug") == PASSWORDLESS_FLOW_SLUG),
        None,
    )
    if flow is None:
        created = client.request(
            "POST",
            "/api/v3/flows/instances/",
            {
                "name": "Use a security key",
                "title": "Use a security key",
                "slug": PASSWORDLESS_FLOW_SLUG,
                "designation": "authentication",
                "authentication": "none",
                "layout": "stacked",
            },
            attempts=3,
        )
        if not isinstance(created, dict) or not created.get("pk"):
            raise AuthentikError("Could not create the security-key flow.")
        flow = created

    flow_pk = str(flow["pk"])
    login_stage = require_stage(client, "user_login", USER_LOGIN_STAGE_NAME)
    wanted = {str(mfa_pk): 10, str(login_stage["pk"]): 100}
    bindings = client.request(
        "GET",
        f"/api/v3/flows/bindings/?target={flow_pk}&page_size=100",
        attempts=3,
    )
    present: set[str] = set()
    for binding in results_of(bindings):
        target = binding.get("target")
        stage = binding.get("stage")
        if isinstance(target, dict):
            target = target.get("pk")
        if isinstance(stage, dict):
            stage = stage.get("pk")
        if str(target or "") != flow_pk:
            continue
        present.add(str(stage))
    for stage_pk, order in wanted.items():
        if stage_pk in present:
            continue
        client.request(
            "POST",
            "/api/v3/flows/bindings/",
            {"target": flow_pk, "stage": stage_pk, "order": order},
            attempts=3,
        )
    return flow_pk


def ensure_totp_device(secret_hex: str) -> None:
    """Enroll akadmin's preview device with the key stored in authentik/.env.

    The admin HTTP API does not accept a TOTP key, so this runs inside the
    server container. The key is passed on stdin and is not printed.
    """
    totp_code(secret_hex)
    script = f"""
from authentik.core.models import User
from authentik.stages.authenticator_totp.models import TOTPDevice
key = {secret_hex.lower()!r}
user = User.objects.get(username="akadmin")
device = TOTPDevice.objects.filter(user=user, name={TOTP_DEVICE_NAME!r}).first()
if device is None:
    TOTPDevice.objects.create(
        user=user,
        name={TOTP_DEVICE_NAME!r},
        confirmed=True,
        digits=6,
        key=key,
    )
elif device.key != key or not device.confirmed or device.digits != 6:
    device.key = key
    device.confirmed = True
    device.digits = 6
    device.last_t = -1
    device.save(update_fields=["key", "confirmed", "digits", "last_t"])
print("RESULT totp-device-ready")
"""
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT / "authentik"),
            "--env-file",
            str(ENV_PATH),
            "-f",
            str(ROOT / "authentik" / "compose.yml"),
            "exec",
            "-T",
            "server",
            "ak",
            "shell",
        ],
        input=script,
        text=True,
        capture_output=True,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    output = output.replace(secret_hex, "[redacted]").replace(secret_hex.lower(), "[redacted]")
    if completed.returncode != 0 or "RESULT totp-device-ready" not in completed.stdout:
        tail = output[-700:].strip()
        raise AuthentikError(f"Could not enroll the akadmin TOTP device. {tail}")


def challenge_value(payload: dict, name: str) -> object:
    """Read a flow field whether the executor used snake_case or camelCase."""
    if name in payload:
        return payload[name]
    parts = name.split("_")
    camel = parts[0] + "".join(part.capitalize() for part in parts[1:])
    return payload.get(camel)


def assert_login_features(client: Client) -> None:
    """Confirm the first login challenge exposes the widgets the theme styles."""
    slug = authentication_flow_slug(client)
    probe = Client(client.base, client.token)
    payload = probe.request(
        "GET",
        f"/api/v3/flows/executor/{slug}/",
        token=False,
        attempts=3,
    )
    if not isinstance(payload, dict):
        raise AuthentikError("Authentication flow probe returned a non-object response.")
    if payload.get("component") != "ak-stage-identification":
        raise AuthentikError("Authentication flow did not open on the identification stage.")
    if challenge_value(payload, "enable_remember_me") is not True:
        raise AuthentikError("Remember me is not enabled on the identification stage.")

    captcha = challenge_value(payload, "captcha_stage")
    js_url = ""
    if isinstance(captcha, dict):
        js_url = str(challenge_value(captcha, "js_url") or "")
    if "turnstile" not in js_url:
        raise AuthentikError("Identification stage is not showing the Turnstile widget.")

    passkey = challenge_value(payload, "passkey_challenge")
    if not isinstance(passkey, dict) or not passkey:
        raise AuthentikError("Identification stage is not offering a passkey challenge.")
    if not challenge_value(payload, "passwordless_url"):
        raise AuthentikError("Identification stage is not offering a security key.")

    security_key = Client(client.base, client.token).request(
        "GET",
        f"/api/v3/flows/executor/{PASSWORDLESS_FLOW_SLUG}/",
        token=False,
        attempts=3,
    )
    if not isinstance(security_key, dict) or security_key.get("component") != (
        "ak-stage-authenticator-validate"
    ):
        raise AuthentikError("Security-key flow did not open on the WebAuthn prompt.")

    print(
        "Login flow shows Remember me, a Turnstile widget, and a security key. "
        "akadmin has a TOTP device for the code stage after the password."
    )


def configure_login_features(client: Client, totp_secret: str) -> None:
    """Turn on the login widgets that matter for the theme. Safe to repeat."""
    captcha_pk = ensure_turnstile_stage(client)
    mfa = require_stage(client, "authenticator/validate", MFA_STAGE_NAME)
    passwordless_pk = ensure_passwordless_flow(client, str(mfa["pk"]))
    client.request(
        "PATCH",
        f"/api/v3/stages/authenticator/validate/{mfa['pk']}/",
        {
            "device_classes": ["totp", "webauthn"],
            "not_configured_action": "skip",
            "webauthn_user_verification": "discouraged",
            "webauthn_hints": ["security-key"],
        },
        attempts=3,
    )
    identification = require_stage(client, "identification", IDENTIFICATION_STAGE_NAME)
    # The serializer checks user_fields from the request body, including on PATCH,
    # so an omitted list is treated as "no fields" and the update is rejected.
    user_fields = identification.get("user_fields") or ["email", "username"]
    client.request(
        "PATCH",
        f"/api/v3/stages/identification/{identification['pk']}/",
        {
            "user_fields": user_fields,
            "enable_remember_me": True,
            "captcha_stage": captcha_pk,
            "webauthn_stage": mfa["pk"],
            "passwordless_flow": passwordless_pk,
        },
        attempts=3,
    )
    ensure_totp_device(totp_secret)
    assert_login_features(client)


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


def login(client: Client, username: str, password: str, totp_secret: str) -> None:
    """Walk the flow executor until Authentik redirects the signed-in user.

    Identification takes the username and the Turnstile test token. Password
    is the next stage. When akadmin has a TOTP device, the validation stage
    asks for the current code. A code Authentik already consumed is retried
    on the following 30-second step.
    """
    slug = authentication_flow_slug(client)
    path = f"/api/v3/flows/executor/{slug}/"
    payload = client.request("GET", path, token=False, attempts=5)
    totp_retries = 0
    seen: list[str] = []

    for _ in range(8):
        if not isinstance(payload, dict):
            raise AuthentikError("Authentication flow returned a non-object response.")

        component = str(payload.get("component") or "")
        if component and (not seen or seen[-1] != component):
            seen.append(component)
        if component in {"xak-flow-redirect", "ak-stage-flow-redirect"}:
            print(f"Logged in as {username} through {slug}.")
            return

        errors = payload.get("response_errors") or {}
        retry_totp = component == "ak-stage-authenticator-validate" and totp_retries < 1
        if errors and not retry_totp:
            raise AuthentikError(
                f"Authentication flow rejected the attempt at {component or 'unknown stage'}."
            )
        if errors and retry_totp:
            totp_retries += 1
            time.sleep(max(1.0, 30 - (time.time() % 30) + 0.5))

        if component == "ak-stage-identification":
            body: dict[str, str] = {
                "uid_field": username,
                "captcha_token": TURNSTILE_DUMMY_TOKEN,
            }
        elif component == "ak-stage-password":
            body = {"password": password}
        elif component == "ak-stage-authenticator-validate":
            wait_for_fresh_totp_window()
            body = {"code": totp_code(totp_secret)}
        elif component in {"ak-stage-user-login", "ak-stage-prompt"}:
            body = {}
        else:
            raise AuthentikError(f"Unsupported authentication stage {component or 'unknown'}.")

        payload = client.request("POST", path, body, token=False, attempts=3)

    raise AuthentikError(
        "Authentication flow did not finish. Stages seen: " + ", ".join(seen or ["none"])
    )


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
    subcommands.add_parser(
        "configure",
        help="enable Remember me, Turnstile, a security key, and a TOTP device",
    )
    subcommands.add_parser("features", help="check that the login challenge exposes those widgets")
    subcommands.add_parser("login", help="sign in as akadmin through the authentication flow")
    subcommands.add_parser("totp", help="print akadmin's current 6-digit TOTP code")
    subcommands.add_parser("deploy", help="publish the theme, then sign in")
    args = parser.parse_args()

    try:
        client = build_client(args.base_url)
        env = load_env(ENV_PATH)
        if args.command == "wait":
            wait_until_ready(client, args.timeout)
        elif args.command == "apply":
            apply_css(client, CSS_PATH)
        elif args.command == "configure":
            configure_login_features(client, require(env, "AUTHENTIK_TOTP_SECRET"))
        elif args.command == "features":
            assert_login_features(client)
        elif args.command == "login":
            login(
                client,
                "akadmin",
                require(env, "AUTHENTIK_BOOTSTRAP_PASSWORD"),
                require(env, "AUTHENTIK_TOTP_SECRET"),
            )
        elif args.command == "totp":
            print(totp_code(require(env, "AUTHENTIK_TOTP_SECRET")))
        elif args.command == "deploy":
            apply_css(client, CSS_PATH)
            login(
                client,
                "akadmin",
                require(env, "AUTHENTIK_BOOTSTRAP_PASSWORD"),
                require(env, "AUTHENTIK_TOTP_SECRET"),
            )
        else:
            raise AuthentikError(f"Unknown command {args.command}.")
    except (AuthentikError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
