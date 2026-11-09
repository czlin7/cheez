# Email delivery

With email on, each edition also arrives in your inbox as a short digest, in
the style of a morning newsletter: the TL;DR, Today's playbook (price, a
three-month text sparkline, why, outlook, entry · invalidation · target),
the market pulse, the brief, what is coming up, and a button to the full page.
It is written in `email.language` (default: the page's default language), and
prices carry `(≈ £…)` when `email.convert_to` or `report.convert_to` is set.

```bash
cheez email            # build var/site/email.html and email.eml (a preview; nothing is sent)
cheez email --send     # send to the configured recipients (once per edition revision)
```

`cheez demo` writes a preview of the fictional edition to
`var/demo/site-demo/email.html`.

## Turn it on

```toml
[email]
enabled = true
to = ["you@example.com"]
from = "Cheez Daily <you@example.com>"
page_url = "https://claude.ai/code/artifact/…"   # your private page, for the button
```

Then choose a provider.

### SMTP (Gmail, Outlook, Fastmail, …)

```toml
provider = "smtp"
smtp_host = "smtp.gmail.com"     # Outlook/Hotmail: smtp-mail.outlook.com; Microsoft 365: smtp.office365.com
smtp_port = 587
smtp_user = "you@gmail.com"
```

Put the password in the environment as `CHEEZ_SMTP_PASSWORD`. For Gmail this
must be an [app password](https://myaccount.google.com/apppasswords) (it
requires 2-step verification); never use your account password.

**Cloud sessions:** many cloud sandboxes, including Claude Code's, only allow
outbound HTTPS through a proxy, so SMTP on port 587 is usually blocked there.
Use SMTP for local runs and Resend for scheduled cloud runs.

### Resend (HTTPS API; works in cloud sessions)

```toml
provider = "resend"
from = "Cheez Daily <brief@your-verified-domain.example>"
```

Create an API key at resend.com (the free tier covers a daily email) and
verify a sending domain, or use `onboarding@resend.dev` to send only to your
own address while testing. Provide the key either as `CHEEZ_RESEND_API_KEY`,
or, in a Claude Code cloud environment, as a **network secret** for the host
`api.resend.com` (header `Authorization`, prefix `Bearer`): the environment's
proxy then adds it to Cheez's requests and the key never appears inside the
session. Allow `api.resend.com` in the environment's network settings if your
policy is limited.

## In the scheduled run

When `cheez config` shows email enabled, the skill runs
`.venv/bin/cheez email --send` right after publishing the page. The send is
recorded per edition revision, so a retried step does not email you twice
(`--force` overrides).

> **Note for the Cheez environment (Longbridge token present):** the guard
> hook's lockdown allowlist predates this command and blocks
> `cheez email`, `cheez config` and `cheez schedule` until it is extended.
> See SECURITY.md, "Pending guard update".

## Privacy

Email is stored by your provider and the recipient's mailbox, outside the
private page. So:

- The portfolio section is **left out** unless you set
  `include_portfolio = true` (then only the editorial portfolio summary is
  included: no quantities, values or account details).
- Recipients come only from settings or the environment; there is no command
  line flag that can send the digest elsewhere.
- Settings files with addresses are gitignored (`cheez.toml`); in the cloud,
  keep them in the environment's variables, which are private to you.
