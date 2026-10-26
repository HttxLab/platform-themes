# Authentik theme loop

Edit `authentik/style.css`, then publish it to the local Authentik and check the login page. Do not commit `authentik/.env`, and do not print the password or API token from that file.

## Deploy

From the repository root:

```bash
.scripts/authentik/deploy.sh
```

The command starts the Compose stack in `authentik/compose.yml` when it is not already up, waits until the default brand exists, enables the login widgets below, patches that brand's `branding_custom_css`, and signs in as `akadmin` through `default-authentication-flow`. Run it again after every CSS change. A second run reuses the database and `.env`.

Login page: http://127.0.0.1:9000/if/flow/default-authentication-flow/

The public check is `GET http://127.0.0.1:9000/api/v3/core/brands/current/`. `branding_custom_css` should contain `--abyss-accent`.

## Login widgets

`up.sh` calls `api.py configure`, which turns on the parts of a real login page that this theme styles:

- Remember me, on the identification stage
- A visible Cloudflare Turnstile test widget (site key `1x00000000000000000000AA`, the published always-pass key)
- A security-key button. It opens a short passwordless flow whose first screen is the WebAuthn prompt. The username field also gets a passkey challenge for conditional UI
- A TOTP code prompt after the password, because `akadmin` has one confirmed device

Duo, SMS, email, and static tokens are left off. The MFA stage still skips users who have no device.

The Turnstile widget script loads from Cloudflare in the browser. The Authentik container cannot call Cloudflare's siteverify from this environment, so `captcha-verify` in `authentik/compose.yml` answers that check locally and accepts the test token. `.scripts/authentik/login.sh` submits that token and the current TOTP code. Print the code, not the secret, with `.scripts/authentik/totp.sh`. The secret is `AUTHENTIK_TOTP_SECRET` in `authentik/.env`.

## Visual check

```bash
.scripts/authentik/preview.sh
```

Headless Chrome writes `/tmp/authentik-login.png` and fails if the rendered DOM does not contain `--abyss-accent`. Chrome exiting on the timeout is expected when the screenshot and DOM were written.

## Other commands

| Command | Use |
| --- | --- |
| `.scripts/authentik/up.sh` | Start Authentik, wait for the default brand, and enable the login widgets |
| `.scripts/authentik/configure.sh` | Enable the widgets again without publishing CSS |
| `.scripts/authentik/login.sh` | Sign in as `akadmin` without publishing CSS |
| `.scripts/authentik/totp.sh` | Print akadmin's current 6-digit TOTP code |
| `.scripts/authentik/down.sh` | Stop the containers and keep the database |
| `.scripts/authentik/down.sh --volumes` | Delete the database. Also delete `authentik/.env` before the next deploy so bootstrap matches the new token |
| `.scripts/authentik/api.py` | `wait`, `configure`, `features`, `apply`, `login`, `totp`, and `deploy` |

`.scripts/authentik/api.py` is what the shell scripts call. Credentials are `AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_TOKEN`, and `AUTHENTIK_TOTP_SECRET` in `authentik/.env`. Do not print those values.

## Docker

If `docker info` fails, run `.scripts/cloud-agent/start.sh`. On a Cloud Agent boot that script starts the daemon, then runs `.scripts/authentik/deploy.sh` when `authentik/compose.yml` and `authentik/style.css` are in the checkout. `.scripts/cloud-agent/install.sh` installs Docker and pulls `postgres:16-alpine` and `ghcr.io/goauthentik/server:2026.8.5`. It is for environment setup, not for a CSS edit.

Container-to-container traffic needs `net.bridge.bridge-nf-call-iptables=0`. `start.sh` sets that before launching `dockerd`.
