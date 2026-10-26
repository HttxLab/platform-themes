# Authentik theme loop

Edit `authentik/style.css`, then publish it to the local Authentik and check the login page. Do not commit `authentik/.env`, and do not print the password or API token from that file.

## Deploy

From the repository root:

```bash
.scripts/authentik/deploy.sh
```

The command starts the Compose stack in `authentik/compose.yml` when it is not already up, waits until the default brand exists, patches that brand's `branding_custom_css`, and signs in as `akadmin` through `default-authentication-flow`. Run it again after every CSS change. A second run reuses the database and `.env`.

Login page: http://127.0.0.1:9000/if/flow/default-authentication-flow/

The public check is `GET http://127.0.0.1:9000/api/v3/core/brands/current/`. `branding_custom_css` should contain `--abyss-accent`.

## Visual check

```bash
.scripts/authentik/preview.sh
```

Headless Chrome writes `/tmp/authentik-login.png` and fails if the rendered DOM does not contain `--abyss-accent`. Chrome exiting on the timeout is expected when the screenshot and DOM were written.

## Other commands

| Command | Use |
| --- | --- |
| `.scripts/authentik/up.sh` | Start Authentik and wait for the default brand |
| `.scripts/authentik/login.sh` | Sign in as `akadmin` without publishing CSS |
| `.scripts/authentik/down.sh` | Stop the containers and keep the database |
| `.scripts/authentik/down.sh --volumes` | Delete the database. Also delete `authentik/.env` before the next deploy so bootstrap matches the new token |
| `.scripts/authentik/api.py` | `wait`, `apply`, `login`, and `deploy` against the HTTP API |

`.scripts/authentik/api.py` is what the shell scripts call. Credentials are `AUTHENTIK_BOOTSTRAP_PASSWORD` and `AUTHENTIK_BOOTSTRAP_TOKEN` in `authentik/.env`.

## Docker

If `docker info` fails, run `.scripts/cloud-agent/start.sh`. On a Cloud Agent boot that script starts the daemon, then runs `.scripts/authentik/deploy.sh` when `authentik/compose.yml` and `authentik/style.css` are in the checkout. `.scripts/cloud-agent/install.sh` installs Docker and pulls `postgres:16-alpine` and `ghcr.io/goauthentik/server:2026.8.5`. It is for environment setup, not for a CSS edit.

Container-to-container traffic needs `net.bridge.bridge-nf-call-iptables=0`. `start.sh` sets that before launching `dockerd`.
