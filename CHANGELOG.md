# Changelog

## 1.1.0 — 2026-10-28

- Add `--owner` for a compact summary focused on registrant organizations, names, contact countries, and email addresses.
- Combine registry and registrar information by default in domain owner mode, while respecting explicit source-selection options.
- Support focused JSON output with `--owner --raw` and offline summaries with `--owner --file`.
- Keep registrar, technical, administrative, abuse, and unrelated nested contacts out of owner summaries.

## 1.0.1 — 2026-10-28

- Make English the primary edition on `main`, including command-line help, diagnostics, labels, documentation, and source comments.
- Preserve the original French edition on the `fr` branch.
- Default `Accept-Language` to `en`, independently of the system locale. The `--language` option continues to control the response language requested from RDAP servers.
- Publish matching English distributions with the `rdappy` console command.

## 1.0.0 — 2026-10-28

- Standalone RDAP client in a single Python module, with no runtime dependencies.
- Installable `rdappy` command on Windows, Linux, and macOS.
- Support for domain names, TLDs, IPv4/IPv6 and CIDR prefixes, ASNs, entities, and nameservers.
- IANA bootstrap discovery and registrar referrals.
- Domain search, JSON output, short output, and local JSON input.
- jCard contacts, DNSSEC, events, statuses, TTL values, notices, and redacted fields.
- Origin-scoped authentication, TLS verification, and optional caching.
- Wheel and source distributions, SHA-256 checksums, and offline tests.
