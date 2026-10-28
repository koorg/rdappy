# rdappy

A command-line RDAP client written in Python. The application fits in a single file and uses only the standard library: no runtime dependencies and no native compilation.

Query registration data for domain names, IP addresses and networks, autonomous systems, contacts, and nameservers.

**Python 3.10 or later · Windows, Linux, and macOS · Perl Artistic License 1.0**

The English edition is maintained on `main`. The original French edition is preserved on the [`fr` branch](https://github.com/koorg/rdappy/tree/fr).

## Installation

[GitHub releases](https://github.com/koorg/rdappy/releases) include a universal wheel. After downloading it:

```console
python -m pip install --user --no-deps rdappy-1.0.1-py3-none-any.whl
rdappy --version
rdappy example.com
```

Omit `--user` when using an activated virtual environment. The installer creates the `rdappy` command automatically (`rdappy.exe` on Windows). Its scripts directory must be on `PATH`. If the command is not found, add that directory to `PATH` and open a new terminal, or use `python -m rdappy`.

For an isolated installation with an existing `pipx` installation:

```console
pipx install ./rdappy-1.0.1-py3-none-any.whl
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

## Usage

```console
rdappy example.com
rdappy --registry --short example.com
rdappy --both --raw rdap.org
rdappy 1.1.1.1
rdappy 2606:4700:4700::1111
rdappy 192.0.2.0/24
rdappy AS13335
rdappy --tld com
rdappy --entity ADMIN2521-ARIN
rdappy --nameserver a.root-servers.net
rdappy --reverse 1.1.1.1
rdappy --search nic.fr
rdappy --search "exampl*.com"
rdappy https://rdap.org/domain/example.com
rdappy --file response.json --raw
rdappy --help
```

Server discovery uses the IANA bootstrap registries. By default, rdappy follows a registrar referral when one is available. If that request fails, it displays the registry record and writes a warning to standard error.

| Option | Behavior |
| --- | --- |
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
rdappy-1.0.1-py3-none-any.whl
rdappy-1.0.1.tar.gz
rdappy.py
SHA256SUMS
```

The wheel contains the single application module and its metadata. The source archive also includes the documentation, tests, and build tool. Archive timestamps and metadata are normalized to make builds reproducible with identical sources and tools. Set `SOURCE_DATE_EPOCH` to choose an explicit reference timestamp.

Tests use only Python and a loopback HTTP server. They do not access the Internet:

```console
python -B -m unittest discover -s tests -v
```

## License and provenance

rdappy implements the functionality of [App::rdapper](https://github.com/gbxyz/rdapper), by CentralNic Ltd. and Gavin Brown, as a separate Python application. Credits, references, and implementation differences are listed in [NOTICE](NOTICE). The [Perl Artistic License 1.0](LICENSE) is also embedded in the application file so it can be distributed on its own.
