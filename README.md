# rdappy

A command-line RDAP client written in Python. The application fits in a single file and uses only the standard library: no runtime dependencies and no native compilation.

Query registration data for domain names, IP addresses and networks, autonomous systems, contacts, and nameservers.

**Python 3.10 or later · Windows, Linux, and macOS · Artistic-1.0-Perl AND BSD-2-Clause**

The English edition is maintained on `main`. The original French edition is preserved on the [`fr` branch](https://github.com/koorg/rdappy/tree/fr).

## Installation

[GitHub releases](https://github.com/koorg/rdappy/releases) include a universal wheel. After downloading it:

```console
python -m pip install --user --no-deps rdappy-1.1.2-py3-none-any.whl
rdappy --version
rdappy example.com
```

Omit `--user` when using an activated virtual environment. The installer creates the `rdappy` command automatically (`rdappy.exe` on Windows). Its scripts directory must be on `PATH`. If the command is not found, add that directory to `PATH` and open a new terminal, or use `python -m rdappy`.

For an isolated installation with an existing `pipx` installation:

```console
pipx install ./rdappy-1.1.2-py3-none-any.whl
```

From a local copy of the repository:

```console
python -m pip install --user --no-deps .
```

Installing from source uses `setuptools` to build the package; the installed application still has no dependencies. Installing the wheel does not require `setuptools`, a compiler, or access to a package index.

The application also runs without installation:

```console
python rdappy.py example.com
```

### Debian and Ubuntu

Download the architecture-independent `.deb` from the same release, then install it:

```console
sudo apt install ./rdappy_1.1.2_all.deb
rdappy --owner example.com
```

The package installs `/usr/bin/rdappy` and requires the distribution's Python 3.10 or later. It has no Python package dependencies, maintainer scripts, or network activity during installation. License notices are installed in `/usr/share/doc/rdappy/`. Remove it with `sudo apt remove rdappy`.

### GitHub Packages

An executable Linux amd64 container is published in [GitHub Packages](https://github.com/users/koorg/packages/container/package/rdappy):

```console
docker run --rm ghcr.io/koorg/rdappy:1.1.2 --owner example.com
docker run --rm ghcr.io/koorg/rdappy:1.1.2 --license
```

The container runs as an unprivileged numeric user. GitHub may require `docker login ghcr.io` when the package is private. The wheel and Debian package are downloadable release assets; GitHub Packages lists the container because it does not provide Python or Debian registries.

## Usage

```console
rdappy example.com
rdappy --owner example.com
rdappy --owner 1.1.2.1
rdappy --registry --short example.com
rdappy --both --raw rdap.org
rdappy 1.1.2.1
rdappy 2606:4700:4700::1111
rdappy 192.0.2.0/24
rdappy AS13335
rdappy --tld com
rdappy --entity ADMIN2521-ARIN
rdappy --nameserver a.root-servers.net
rdappy --reverse 1.1.2.1
rdappy --search nic.fr
rdappy --search "exampl*.com"
rdappy https://rdap.org/domain/example.com
rdappy --file response.json --raw
rdappy --help
```

Server discovery uses the IANA bootstrap registries. By default, rdappy follows a registrar referral when one is available. If that request fails, it displays the registry record and writes a warning to standard error.

| Option | Behavior |
| --- | --- |
| `--owner` | Show a compact registrant summary focused on organizations. For domains, combine registry and registrar data by default. |
| `--registry` | Display only the registry record. |
| `--registrar` | Follow the registrar referral; this is the default. |
| `--both` | Display both registry and registrar records. |
| `--raw`, `--json` | Display complete JSON. Two records or multiple search responses are combined into a valid JSON array. |
| `--short` | Omit links, remarks, notices, and redacted fields. |
| `--type TYPE` | Select `domain`, `tld`, `ip`, `autnum`, `entity`, `nameserver`, or `url`. Options such as `--domain` and `--ip` are aliases. |
| `--server URL` | Explicitly select an RDAP service's base URL. |
| `--search` | Search domain names. Without a suffix, query each distinct IANA DNS service. |
| `--reverse` | Query the reverse DNS zone of the IP's allocated block. For an unaligned block, use the parent reverse zone covering it. |
| `--timeout SECONDS` | Network timeout per request, 20 seconds by default. |
| `--cache-dir DIRECTORY` | Enable disk caching. Ordinary responses are cached for at most 300 seconds, and IANA bootstraps for at most 24 hours. |
| `--bypass-cache` | Bypass caches and do not write to them. |
| `--file JSON` | Read a local response without making RDAP requests or following referrals. |
| `--auth USER:PASS` | Use HTTP Basic authentication with `--server` or an explicit RDAP URL. Credentials are never forwarded to another origin or stored in the cache. |
| `--language LANGUAGE` | Set the `Accept-Language` request header, which defaults to `en`. The application's help, labels, and diagnostics are always English; server-provided data is displayed as received. |
| `--nocolor` | Disable ANSI colors. The `NO_COLOR` environment variable is also respected. |
| `--config FILE`, `--no-config` | Select or ignore the configuration file. |
| `--debug` | Print queried URLs to standard error. |
| `--insecure` | Disable TLS certificate verification for a service whose connection you explicitly control. |
| `--version`, `--license` | Display the version or license. |

Search availability depends on each server's capabilities and access rules. A server may reject wildcards or require authentication. rdappy also accepts the nonstandard `domainSearchResult` field returned by the `.fr` service. Global searches can take time; specify a suffix or `--server` to limit the requests.

Internationalized names use Python's built-in IDNA codec (IDNA 2003). For some IDNA 2008 names, provide the ASCII form accepted by the service directly.

A `404` result means that the object was not found in the queried service. It does not prove that a domain is available for registration. Private addresses, documentation prefixes, and some reserved resources may not have RDAP records.

## Focused registrant summaries

```console
rdappy --owner example.com
rdappy --owner 1.1.2.1
rdappy --owner --raw example.com
rdappy --owner --registry example.com
```

`--owner` displays only the queried domain or network, registrant organizations, contact names, contact countries, and email addresses. Organizations appear first. Missing fields are omitted, while an unavailable organization is explicitly shown as `Not disclosed or not provided`.

Only entities explicitly assigned the `registrant` role on the queried object are used. Registrar, technical, administrative, and abuse contacts are excluded. A network label is never used as an organization name. An entity's formatted name is used as its organization only when its jCard explicitly identifies it as an organization.

For domains, registry and registrar data are combined and duplicate values are removed. Use `--registry` or `--registrar` to select one source explicitly. `--owner --raw` produces focused JSON with `object_type`, `object`, `organizations`, `registrants`, `emails`, `countries`, `sources`, and `country_details` fields; `--raw` without `--owner` continues to return the complete RDAP response.

This mode also supports ASNs and local JSON files. It cannot be combined with `--search`. A network registrant may be an operator or hosting provider, and a domain registrant may be a privacy service; this summary does not identify an undisclosed end user or beneficial owner.

The country indication always identifies its basis:

- `Country (registrant)` comes from the direct registrant's postal address. A valid `cc` parameter takes priority over the country-name component, followed by a recognized country name on the last line of an unstructured postal address. Country names are recognized using an embedded public-domain IANA table; ambiguous state codes and bare `Georgia` lines are ignored.
- `Country (network registration)` or `Country (ASN registration)` uses the record's declared two-letter `country` only when no registrant address country is available.
- `Country: Not disclosed or not provided` means no usable public country was supplied. Conflicting published countries are retained.

These are administrative registration data, not physical IP geolocation. Domain suffixes, registrar addresses and hosting locations are not used to infer a registrant's country. No additional service or database is queried.

In `--owner --raw`, the existing `countries` array remains limited to registrant address countries. Recognized country names and codes are normalized to two-letter codes. The new `country_details` array contains the selected indications with `country`, `basis` (`registrant_address`, `network_registration` or `autnum_registration`), and `source` (the RDAP URL or local file URI). Repeated evidence is deduplicated, and fallback registration data are not presented as registrant addresses.

These fields follow [RDAP registration data](https://www.rfc-editor.org/rfc/rfc9083.html#section-5.4) and the [vCard country-code parameter](https://www.rfc-editor.org/rfc/rfc8605.html#section-3.1).

## Configuration

rdappy reads `~/.rdappy`, falling back to `~/.rdapper` when the first file does not exist. Use one argument per line. Empty lines and comments starting with `#` are ignored.

```text
--short
--language=en
--timeout=15
```

For compatibility with rdapper, these arguments are appended after command-line arguments. A value in the file can therefore override a value entered in the terminal. Use `--no-config` when a command's parameters must be entirely explicit.

The interface remains English regardless of system locale or the requested response language. To use the French edition, switch to the [`fr` branch](https://github.com/koorg/rdappy/tree/fr).

No persistent cache is created unless `--cache-dir` is supplied. Authenticated responses and responses with `Cache-Control: no-store`, `no-cache`, or `private` are not cached. The optional cache contains received RDAP data; choose a directory whose access permissions are appropriate for that data.

## Scripting and exit codes

Results are written to `stdout`. Warnings, diagnostics, and errors are written to `stderr`. Both the installed command and `python -m rdappy` use UTF-8 output, including when redirected.

| Code | Meaning |
| --- | --- |
| `0` | Success. A valid search with no results also succeeds. |
| `1` | Network failure, RDAP error, or invalid data. |
| `2` | Invalid arguments. |
| `130` | Interrupted by the user. |

Responses are limited to 16 MiB. HTTP(S) redirects are bounded, HTTPS-to-HTTP redirects are rejected, and no automatic retry bypasses a `429` response.

## Building distributions

The build uses Python and the `setuptools` version pinned in `pyproject.toml`. It does not compile native components or download anything during the build.

With `setuptools==82.0.1` already installed:

```console
python tools/build.py
```

The following files are created in `dist/`:

```text
rdappy-1.1.2-py3-none-any.whl
rdappy-1.1.2.tar.gz
rdappy_1.1.2_all.deb
rdappy.py
SHA256SUMS
```

The wheel contains the single application module and its metadata. The source archive also includes the documentation, tests, and build tools. Archive timestamps and ownership metadata are normalized to make builds reproducible with identical sources and tools. Set `SOURCE_DATE_EPOCH` to choose an explicit reference timestamp.

Build only the Debian package using Python's standard library, without `setuptools` or Debian build tools:

```console
python -B tools/build.py --deb-only
```

Published author and maintainer fields use the GitHub pseudonym `koorg`. Audit tracked sources, reachable Git history, and explicitly named archives without printing host identifiers:

```console
python -B tools/audit_distribution.py --history --github-profile dist/rdappy-1.1.2-py3-none-any.whl dist/rdappy-1.1.2.tar.gz dist/rdappy_1.1.2_all.deb
```

Omit `--github-profile` for a completely offline audit. Local host identifiers are checked in either mode. The container build context is restricted to the application and its license files.

Tests use only Python and a loopback HTTP server. They do not access the Internet:

```console
python -B -m unittest discover -s tests -v
```

## License and provenance

rdappy implements the functionality of [App::rdapper](https://github.com/gbxyz/rdapper), by CentralNic Ltd. and Gavin Brown, as a separate Python application. Credits, references, and implementation differences are listed in [NOTICE](NOTICE).

The application uses the [Perl Artistic License 1.0](LICENSE). Adaptations based on Net::RDAP also retain its [BSD-2-Clause conditions and disclaimer](LICENSES/BSD-2-Clause.txt), giving the distribution the expression `Artistic-1.0-Perl AND BSD-2-Clause`. Both complete texts are embedded in the single application file and included in the wheel, source archive, Debian package, and container. Run `rdappy --license` to display them. Original copyright holders are credited as required by their licenses.
