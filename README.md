# platform-themes
A collection of CSS themes for different applications so looks stay consistent and easy to reuse.

## Authentik preview

Docker Compose runs a local Authentik so `authentik/style.css` can be published onto the default brand and checked in the login flow.

```bash
./scripts/authentik-deploy.sh
```

That starts Authentik, patches the default brand's custom CSS, and signs in as `akadmin` through the default authentication flow. After a CSS edit, run the same command again.

- UI: http://127.0.0.1:9000/if/flow/default-authentication-flow/
- Credentials: `authentik/.env` (generated on first start, not committed)
- Screenshot check: `./scripts/authentik-preview.sh`
- Stop: `./scripts/authentik-down.sh`
- Fresh database: `./scripts/authentik-down.sh --volumes` and delete `authentik/.env` before the next deploy

Cloud Agents install Docker during setup and run `scripts/cloud-agent-start.sh` on boot, which calls the deploy script when this checkout contains the Authentik stack.
