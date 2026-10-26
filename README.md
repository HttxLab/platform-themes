# platform-themes
A collection of CSS themes for different applications so looks stay consistent and easy to reuse.

## Trying the Authentik theme

Docker and Docker Compose are required. From the repository root:

```bash
.scripts/authentik/deploy.sh
```

That starts a local Authentik, applies `authentik/style.css` to the default brand, and signs in as `akadmin`. After editing the CSS, run the same command again.

The login page includes the widgets the theme styles: Remember me, a Cloudflare Turnstile test widget, and a security-key button. After the password, `akadmin` is asked for a TOTP code. `.scripts/authentik/totp.sh` prints the current code.

- Login page: http://127.0.0.1:9000/if/flow/default-authentication-flow/
- Username: `akadmin`
- Password: `AUTHENTIK_BOOTSTRAP_PASSWORD` in `authentik/.env` (created on first start, not committed)
- TOTP code: `.scripts/authentik/totp.sh`
- Rendered check: `.scripts/authentik/preview.sh`
- Stop: `.scripts/authentik/down.sh`
- Fresh database: `.scripts/authentik/down.sh --volumes`, then delete `authentik/.env` before the next deploy
