# Security Policy

## Supported Versions

psa-cli is pre-1.0. Only the latest release receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.3.x   | Yes       |
| < 0.3   | No        |

## Reporting a Vulnerability

Report security issues privately to **kyle@psadmin.io**. Do not open a public issue.

Include:
- A description of the issue
- Steps to reproduce
- Affected version(s)
- Any suggested fix

You can expect an acknowledgement within 5 business days.

## Known Limitations

- `psa domain list --json` and `psa domain status --json` include raw config content that contains **encrypted** passwords from PeopleSoft config files (issue #23). Values are not cleartext, but the structure may be undesirable in piped output. Fix tracked for v0.4.
- The `psa ops` and `psa kit` command groups depend on psadmin.io infrastructure and are hidden / gated. They are not intended for general public use in this release.
