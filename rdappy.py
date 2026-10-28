#!/usr/bin/env python3
# SPDX-License-Identifier: Artistic-1.0-Perl
"""rdappy: a standalone Registration Data Access Protocol (RDAP) client.

Python 3.10 or later. No runtime dependencies.
Run ``rdappy --help`` or ``python rdappy.py --help`` for usage.

Based on App::rdapper by CentralNic Ltd. and Gavin Brown.
Copyright and licensing information is included in ARTISTIC_LICENSE.
"""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
from http.client import HTTPException
import ipaddress
import json
import locale
import math
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

VERSION = "1.0.0"
IANA = "https://data.iana.org/rdap/"
MAX_BYTES = 16 * 1024 * 1024
SEARCH_KEYS = ("domainSearchResults", "nameserverSearchResults", "entitySearchResults", "domainSearchResult", "nameserverSearchResult", "entitySearchResult")
TYPES = ("domain", "ip", "autnum", "entity", "nameserver", "tld", "url")
EPP_STATUSES = set("addPeriod autoRenewPeriod clientDeleteProhibited clientHold clientRenewProhibited clientTransferProhibited clientUpdateProhibited inactive pendingCreate pendingDelete pendingRenew pendingRestore pendingTransfer pendingUpdate redemptionPeriod renewPeriod serverDeleteProhibited serverRenewProhibited serverTransferProhibited serverUpdateProhibited serverHold transferPeriod".split())


class RdapError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Response:
    data: dict
    url: str


def items(value):
    """Tolerer les champs optionnels absents ou null sans inventer de donnees."""
    return value if isinstance(value, list) else []


def objects(value):
    return [entry for entry in items(value) if isinstance(entry, dict)]


def text(value):
    if isinstance(value, list):
        return "; ".join(text(part) for part in value if part not in (None, ""))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def terminal_text(value):
    # Les donnees RDAP ne doivent pas pouvoir injecter des commandes de terminal.
    return "".join(c for c in text(value) if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) < 160))


def domain_name(value, pattern=False):
    name = value.strip().translate(str.maketrans("\u3002\uff0e\uff61", "..."))
    name = name.removesuffix(".")
    labels = []
    try:
        for label in name.split("."):
            if pattern and "*" in label:
                if not all(c.isalnum() or c in "-*" for c in label):
                    raise ValueError
                encoded = label.lower()
            else:
                encoded = label.encode("idna").decode("ascii").lower()
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", encoded):
                    raise ValueError
                if encoded.startswith("xn--"):
                    decoded = encoded[4:].encode("ascii").decode("punycode")
                    if decoded.isascii():
                        raise ValueError
            if not 1 <= len(encoded.encode("utf-8")) <= 63:
                raise ValueError
            labels.append(encoded)
        result = ".".join(labels)
        if len(result.encode("utf-8")) > 253:
            raise ValueError
        return result
    except (ValueError, UnicodeError):
        raise RdapError(f"Nom de domaine invalide : {value!r}") from None


def ip_network(value):
    try:
        if "%" in value:
            raise ValueError
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise RdapError(f"Adresse ou prefixe IP invalide : {value!r}") from None


def as_number(value):
    number = re.sub(r"^asn?", "", value, flags=re.I)
    if not re.fullmatch(r"[0-9]{1,10}", number) or int(number) > 4294967295:
        raise RdapError(f"Numero AS invalide : {value!r}")
    return int(number)


def detect_type(value):
    if re.match(r"^(?:https?|file)://", value, re.I):
        return "url"
    if re.match(r"^asn?[0-9]+$", value, re.I) or value.isdecimal():
        return "autnum"
    if ":" in value or "/" in value or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", value):
        return "ip"
    return "tld" if "." not in value.rstrip(".") else "domain"


def reverse_network(name):
    """Convertir une zone inverse en reseau, sans perdre les labels zero."""
    name = name.lower().rstrip(".")
    if name.endswith(".in-addr.arpa"):
        labels = name[:-13].split(".")
        if not 1 <= len(labels) <= 4 or not all(re.fullmatch(r"[0-9]{1,3}", x) and int(x) < 256 for x in labels):
            raise RdapError(f"Zone inverse IPv4 invalide : {name}")
        return ip_network(".".join(list(reversed(labels)) + ["0"] * (4 - len(labels))) + f"/{len(labels) * 8}")
    if name.endswith(".ip6.arpa"):
        labels = name[:-9].split(".")
        if not 1 <= len(labels) <= 32 or not all(re.fullmatch(r"[0-9a-f]", x) for x in labels):
            raise RdapError(f"Zone inverse IPv6 invalide : {name}")
        number = int("".join(reversed(labels)).ljust(32, "0"), 16)
        return ip_network(f"{ipaddress.IPv6Address(number)}/{len(labels) * 4}")
    return None


def reverse_name(network):
    # Aux limites non alignees, utiliser la zone parente couvrant le bloc.
    step = 8 if network.version == 4 else 4
    count = network.prefixlen // step
    if network.version == 4:
        labels = str(network.network_address).split(".")[:count]
        suffix = "in-addr.arpa"
    else:
        labels = network.network_address.exploded.replace(":", "")[:count]
        suffix = "ip6.arpa"
    return ".".join([*reversed(labels), suffix])


def network_from_record(data):
    try:
        start = ipaddress.ip_address(data["startAddress"])
        end = ipaddress.ip_address(data["endAddress"])
        if start.version != end.version or int(end) < int(start):
            raise ValueError
        prefix = start.max_prefixlen - (int(start) ^ int(end)).bit_length()
        return ipaddress.ip_network(f"{start}/{prefix}", strict=False)
    except (KeyError, ValueError, TypeError):
        raise RdapError("La reponse ne contient pas une plage IP valide.") from None


def http_url(url):
    try:
        if not isinstance(url, str) or "\\" in url:
            raise ValueError
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError
        parsed.port  # Valider aussi le port.
        if any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError
        return urlunsplit(parsed._replace(fragment=""))
    except ValueError:
        raise RdapError(f"URL HTTP(S) invalide : {url!r}") from None


def origin(url):
    p = urlsplit(http_url(url))
    port = p.port if p.port is not None else (443 if p.scheme == "https" else 80)
    return p.scheme, p.hostname.lower(), port


def endpoint(base, kind, value=""):
    base = http_url(base)
    p = urlsplit(base)
    path = p.path.rstrip("/") + "/" + kind
    if value != "":
        path += "/" + quote(str(value), safe="/" if kind == "ip" else "")
    return urlunsplit(p._replace(path=path, query="", fragment=""))


def service_base(url):
    p = urlsplit(http_url(url))
    path = re.split(r"/(?:domain|ip|autnum|entity|nameserver)(?:/|$)", p.path, maxsplit=1)[0]
    return urlunsplit(p._replace(path=path.rstrip("/") + "/", query="", fragment=""))


def reject_json_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def decode_document(raw, url):
    try:
        data = json.loads(raw, parse_constant=reject_json_constant, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError):
        raise RdapError(f"Reponse JSON invalide : {url}") from None
    if not isinstance(data, dict):
        raise RdapError(f"La reponse JSON doit etre un objet : {url}")
    if "errorCode" in data:
        code = data["errorCode"]
        description = text(data.get("description"))
        raise RdapError(f"{code} {text(data.get('title', 'Erreur RDAP'))}" + (f" : {description}" if description else ""), code if isinstance(code, int) else None)
    return Response(data, url)


def local_document(value):
    if value.lower().startswith("file://"):
        parsed = urlsplit(value)
        if parsed.netloc not in ("", "localhost"):
            raise RdapError("Les URL file:// distantes ne sont pas prises en charge.")
        path = unquote(parsed.path)
        if os.name == "nt" and re.match(r"^/[a-z]:", path, re.I):
            path = path[1:]
    else:
        path = value
    try:
        with open(path, "rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise RdapError(f"Lecture impossible : {path} : {exc}") from None
    if len(raw) > MAX_BYTES:
        raise RdapError("Le fichier JSON depasse 16 Mio.")
    return decode_document(raw, Path(path).resolve().as_uri())


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = http_url(newurl)
        if urlsplit(req.full_url).scheme == "https" and urlsplit(newurl).scheme == "http":
            raise RdapError("Redirection HTTPS vers HTTP refusee.")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
            if origin(req.full_url) == origin(newurl) and req.get_header("Authorization"):
                redirected.add_unredirected_header("Authorization", req.get_header("Authorization"))
        return redirected


class Client:
    def __init__(self, *, timeout=20, cache_dir=None, bypass=False, auth=None, language="en", debug=False, insecure=False):
        self.timeout, self.bypass, self.auth = timeout, bypass, auth
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.language, self.debug = language, debug
        self.memory = {}
        self.auth_origin = None
        context = ssl.create_default_context()
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = build_opener(SafeRedirect(), HTTPSHandler(context=context))

    def trace(self, message):
        if self.debug:
            print("Debug: " + terminal_text(message), file=sys.stderr)

    def cache_read(self, url):
        if self.bypass:
            return None
        entry = self.memory.get(url)
        if entry is None and self.cache_dir:
            path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
            try:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 4096)
                entry = json.loads(raw, parse_constant=reject_json_constant, parse_float=finite_float)
            except (OSError, ValueError, RecursionError):
                return None
        if isinstance(entry, dict) and entry.get("url") == url:
            expires = entry.get("expires")
            if isinstance(expires, (int, float)) and 0 <= expires <= 1e12 and time.time() < expires and isinstance(entry.get("data"), dict):
                final = entry.get("final_url", url)
                try:
                    if not isinstance(final, str):
                        return None
                    http_url(final)
                except RdapError:
                    return None
                self.trace(f"cache {url}")
                return Response(entry["data"], final)
        return None

    def cache_write(self, url, response, ttl):
        if self.bypass or ttl <= 0:
            return
        entry = {"url": url, "final_url": response.url, "expires": time.time() + ttl, "data": response.data}
        self.memory[url] = entry
        if self.cache_dir:
            temporary = None
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir, delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(entry, stream, ensure_ascii=False)
                os.replace(temporary, path)
            except OSError as exc:
                self.trace(f"cache disque indisponible : {exc}")
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def fetch(self, url, *, authenticated=False, ttl=300):
        url = http_url(url)
        use_auth = bool(authenticated and self.auth)
        if use_auth and self.auth_origin is None:
            self.auth_origin = origin(url)
        use_auth = use_auth and origin(url) == self.auth_origin
        cached = self.cache_read(url) if not use_auth else None
        if cached is not None:
            return cached
        headers = {"Accept": "application/rdap+json, application/json;q=0.9", "User-Agent": f"rdappy/{VERSION}", "Accept-Language": self.language}
        request = Request(url, headers=headers)
        if use_auth:
            token = base64.b64encode(self.auth.encode("utf-8")).decode("ascii")
            request.add_unredirected_header("Authorization", "Basic " + token)
        self.trace(f"GET {url}")
        try:
            with self.opener.open(request, timeout=self.timeout) as stream:
                raw = stream.read(MAX_BYTES + 1)
                final_url = http_url(stream.geturl())
                cache_control = stream.headers.get("Cache-Control", "").lower()
        except HTTPError as exc:
            try:
                try:
                    raw = exc.read(MAX_BYTES + 1)
                except (OSError, HTTPException):
                    raw = b""
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                message = f"HTTP {exc.code} : {text(data.get('title') or exc.reason)}"
                if data.get("description"):
                    message += " : " + text(data["description"])
                if exc.headers.get("Retry-After"):
                    message += " (Retry-After: " + exc.headers["Retry-After"] + ")"
                raise RdapError(f"{message} [{url}]", exc.code) from None
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError, ValueError, HTTPException) as exc:
            raise RdapError(f"Requete impossible : {url} : {getattr(exc, 'reason', exc)}") from None
        if len(raw) > MAX_BYTES:
            raise RdapError(f"La reponse depasse 16 Mio : {url}")
        response = decode_document(raw, final_url)
        if not use_auth and not any(directive in cache_control for directive in ("no-store", "no-cache", "private")):
            age = re.search(r"(?:^|,)\s*max-age\s*=\s*\"?([0-9]+)", cache_control)
            max_age = int(age.group(1)[:9]) if age else ttl
            self.cache_write(url, response, min(ttl, max_age))
        return response

    def services(self, name):
        data = self.fetch(IANA + name + ".json", ttl=86400).data
        services = data.get("services")
        if not isinstance(services, list):
            raise RdapError(f"Bootstrap IANA {name} invalide.")
        result = []
        for entry in services:
            # object-tags contient [contacts, tags, urls], les autres [cles, urls].
            if not isinstance(entry, list) or len(entry) != (3 if name == "object-tags" else 2):
                continue
            keys, urls = entry[-2:]
            valid = [url for url in items(urls) if isinstance(url, str) and url.startswith(("https://", "http://"))]
            valid.sort(key=lambda url: not url.startswith("https://"))
            if valid:
                result.append(([key for key in items(keys) if isinstance(key, str)], valid))
        return result

    def bases(self, kind, value):
        if kind in ("domain", "nameserver"):
            reverse = reverse_network(value)
            if reverse is not None:
                return self.bases("ip", str(reverse))
            matches = [(len(key), urls) for keys, urls in self.services("dns") for key in keys if value == key or value.endswith("." + key) or key == ""]
            if matches:
                return max(matches, key=lambda match: match[0])[1]
        elif kind == "ip":
            network = ip_network(value)
            matches = []
            for keys, urls in self.services("ipv4" if network.version == 4 else "ipv6"):
                for key in keys:
                    registered = ip_network(key)
                    if registered.version == network.version and network.subnet_of(registered):
                        matches.append((registered.prefixlen, urls))
            if matches:
                return max(matches, key=lambda match: match[0])[1]
        elif kind == "autnum":
            number = as_number(value)
            matches = []
            for keys, urls in self.services("asn"):
                for key in keys:
                    if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", key):
                        continue
                    bounds = key.split("-", 1)
                    low, high = int(bounds[0]), int(bounds[-1])
                    if low <= number <= high:
                        matches.append((high - low, urls))
            if matches:
                return min(matches, key=lambda match: match[0])[1]
        elif kind == "entity":
            if "-" not in value:
                raise RdapError("Un handle d'entite doit avoir un tag (ex. ADMIN2521-ARIN), ou utiliser --server.")
            tag = value.rsplit("-", 1)[-1].lower()
            for keys, urls in self.services("object-tags"):
                if tag in [key.lower() for key in keys]:
                    return urls
        raise RdapError(f"Aucun service RDAP IANA pour {value!r}. Utiliser --server URL si un serveur est connu.")

    def candidates(self, urls):
        for index, url in enumerate(urls):
            try:
                return self.fetch(url, authenticated=True)
            except RdapError as exc:
                if index == len(urls) - 1 or (exc.status is not None and exc.status < 500):
                    raise
                self.trace(f"Echec du serveur, essai suivant : {exc}")
        raise RdapError("Aucun serveur RDAP disponible.")

    def lookup(self, value, kind=None, *, server=None, reverse=False):
        kind = kind or detect_type(value)
        if kind == "url":
            return local_document(value) if value.lower().startswith("file://") else self.fetch(value, authenticated=True)
        if kind in ("domain", "nameserver", "tld"):
            value = domain_name(value)
            if kind == "tld" and "." in value:
                raise RdapError("--tld attend un seul label, par exemple fr ou com.")
        elif kind == "ip":
            network = ip_network(value)
            value = str(network) if "/" in value else str(network.network_address)
        elif kind == "autnum":
            value = str(as_number(value))
        endpoint_kind = "domain" if kind == "tld" else kind
        bases = [server] if server else (["https://rdap.iana.org/"] if kind == "tld" else self.bases(kind, value))
        response = self.candidates([endpoint(base, endpoint_kind, value) for base in bases])
        if reverse and kind == "ip":
            zone = reverse_name(network_from_record(response.data))
            response = self.fetch(endpoint(service_base(response.url), "domain", zone), authenticated=True)
        return response

    def records(self, response, mode="registrar"):
        if mode == "registry" or response.data.get("objectClassName") != "domain" or urlsplit(response.url).scheme == "file":
            return [response]
        for link in objects(response.data.get("links")):
            media = text(link.get("type")).split(";", 1)[0].lower().strip()
            if link.get("rel") == "related" and media == "application/rdap+json" and link.get("href"):
                url = urljoin(response.url, text(link["href"]))
                if url == response.url:
                    continue
                try:
                    registrar = self.fetch(url, authenticated=True)
                    if registrar.data.get("objectClassName") != "domain":
                        raise RdapError("La reponse du registrar ne contient pas un objet domaine RDAP.")
                    return [response, registrar] if mode == "both" else [registrar]
                except RdapError as exc:
                    print("Avertissement : renvoi registrar indisponible; resultat du registre conserve. " + terminal_text(exc), file=sys.stderr)
                    return [response]
        return [response]

    def search(self, pattern, *, server=None):
        pattern = domain_name(pattern, pattern=True)
        if server:
            bases = [server]
        elif "." in pattern:
            bases = self.bases("domain", pattern)
        else:
            bases = list(dict.fromkeys(urls[0] for _, urls in self.services("dns")))
        responses = []
        for base in bases:
            url = endpoint(base, "domains") + "?" + urlencode({"name": pattern})
            try:
                result = self.fetch(url, authenticated=True)
                if not any(isinstance(result.data.get(key), list) for key in ("domainSearchResults", "domainSearchResult")):
                    raise RdapError("La reponse ne contient pas domainSearchResults.")
                responses.append(result)
            except RdapError as exc:
                print("Avertissement : " + terminal_text(exc), file=sys.stderr)
        if not responses:
            raise RdapError("La recherche n'a abouti sur aucun serveur RDAP.")
        return responses


FRENCH = {
    "Object type": "Type d'objet", "Domain Name": "Nom de domaine", "IP Network": "Réseau IP",
    "Autonomous System": "Système autonome", "Entity": "Entité", "Nameserver": "Serveur DNS",
    "Help": "Aide", "Name": "Nom", "Handle": "Identifiant", "Type": "Type", "Country": "Pays",
    "Range": "Plage", "Parent": "Parent", "IP Address": "Adresse IP", "DNSSEC signed": "Zone signée DNSSEC",
    "DNSSEC delegation signed": "Délégation signée DNSSEC", "DS Record": "Enregistrement DS",
    "DNSKEY Record": "Enregistrement DNSKEY", "Status": "Statut", "Registration": "Création",
    "Reregistration": "Réenregistrement", "Last changed": "Dernière modification", "Expiration": "Expiration",
    "Deletion": "Suppression", "Transfer": "Transfert", "Locked": "Verrouillage", "Unlocked": "Déverrouillage",
    "Last update of RDAP database": "Dernière mise à jour RDAP", "Registrar expiration": "Expiration chez le registrar",
    "Registrant": "Titulaire", "Administrative": "Administratif", "Technical": "Technique", "Billing": "Facturation",
    "Abuse": "Abus", "Registrar": "Registrar", "Reseller": "Revendeur", "Sponsor": "Parrain", "Proxy": "Mandataire",
    "Contact": "Contact", "Address": "Adresse", "Street": "Rue", "City": "Ville", "State/Province": "Région",
    "Postal Code": "Code postal", "PO Box": "Boîte postale", "Phone": "Téléphone", "Organization": "Organisation",
    "Website": "Site web", "Title": "Titre", "Role": "Rôle", "Kind": "Catégorie", "Categories": "Catégories",
    "Messaging": "Messagerie", "Contact Link": "Lien de contact", "Location": "Localisation", "Profile": "Profil",
    "Notice": "Avis", "Remark": "Remarque", "Link": "Lien", "Redacted Fields": "Champs masqués",
    "Reason": "Motif", "Registration Type": "Type d'enregistrement", "Platform Nameserver": "Serveur DNS de plateforme",
    "Art Record": "Fiche artistique", "DNS TTL Values": "Valeurs TTL DNS", "yes": "oui", "no": "non",
}


class Formatter:
    def __init__(self, *, short=False, color=False, language="en", width=None):
        self.short, self.color = short, color
        self.fr = language.lower().startswith("fr")
        self.width = max(40, width or shutil.get_terminal_size((100, 24)).columns)
        self.lines = []

    def tr(self, label):
        label = text(label)
        return FRENCH.get(label, label) if self.fr else label

    def kv(self, label, value="", indent=0):
        label = terminal_text(self.tr(label)) + ":"
        value = terminal_text(value)
        prefix = "  " * indent
        line = label + (" " + value if value else "")
        wrapped = textwrap.wrap(line, width=max(20, self.width - len(prefix)), subsequent_indent="  ", break_long_words=False, break_on_hyphens=False) or [label]
        if self.color:
            wrapped[0] = wrapped[0].replace(label, "\x1b[1m" + label + "\x1b[0m", 1)
        self.lines.extend(prefix + part for part in wrapped)

    def vcard(self, data, indent):
        card = data.get("vcardArray")
        if not isinstance(card, list) or len(card) != 2:
            return
        labels = {"source": "Source", "kind": "Kind", "fn": "Name", "title": "Title", "role": "Role", "org": "Organization", "geo": "Location", "email": "Email", "contact-uri": "Contact Link", "socialprofile": "Profile", "tel": "Phone", "impp": "Messaging", "url": "Website", "categories": "Categories", "note": "Note", "adr": "Address"}
        properties = [p for p in items(card[1]) if isinstance(p, list) and len(p) >= 4 and isinstance(p[0], str) and p[0] != "version"]
        for prop in sorted(properties, key=lambda p: list(labels).index(p[0]) if p[0] in labels else len(labels)):
            key, params, _, value = prop[:4]
            params = params if isinstance(params, dict) else {}
            if value in (None, "", []) and not params.get("label"):
                continue
            if key == "adr":
                self.kv("Address", indent=indent)
                if params.get("label"):
                    for line in text(params["label"]).splitlines():
                        self.lines.append("  " * (indent + 1) + terminal_text(line))
                else:
                    address = items(value)
                    for i, label in enumerate(("PO Box", "Extended address", "Street", "City", "State/Province", "Postal Code", "Country")):
                        if i < len(address) and address[i]:
                            self.kv(label, text(address[i]), indent + 1)
                if params.get("cc"):
                    self.kv("Country", params["cc"], indent + 1)
            else:
                label = labels.get(key, text(key).capitalize())
                if key == "tel" and "fax" in text(params.get("type")).lower():
                    label = "Fax"
                self.kv(label, text(value), indent)

    def nameserver(self, data, indent):
        if data.get("handle"):
            self.kv("Handle", data["handle"], indent)
        addresses = data.get("ipAddresses")
        if isinstance(addresses, dict):
            for version in ("v4", "v6"):
                for address in items(addresses.get(version)):
                    self.kv("IP Address", address, indent)
        self.ttl(data, indent)

    def ttl(self, data, indent):
        ttl = data.get("ttl0_data")
        if not isinstance(ttl, dict) or not isinstance(ttl.get("values"), dict):
            return
        self.kv("DNS TTL Values", indent=indent)
        for record_type, seconds in sorted(ttl["values"].items()):
            self.kv(record_type, f"{text(seconds)} s", indent + 1)
        if not self.short:
            self.extras({"remarks": ttl.get("remarks")}, indent + 1)

    def extras(self, data, indent):
        for link in objects(data.get("links")):
            if link.get("rel") != "self" and link.get("href"):
                self.kv(link.get("title") or text(link.get("rel") or "Link").capitalize(), link["href"], indent)
        for field, default in (("remarks", "Remark"), ("notices", "Notice")):
            for notice in objects(data.get(field)):
                self.kv(notice.get("title") or notice.get("type") or default, text(notice.get("description")), indent)
                for link in objects(notice.get("links")):
                    if link.get("href"):
                        self.kv(link.get("title") or "Link", link["href"], indent + 1)
        for redaction in objects(data.get("redacted")):
            name, reason = redaction.get("name"), redaction.get("reason")
            if isinstance(name, dict):
                name = name.get("description") or name.get("type")
            if isinstance(reason, dict):
                reason = reason.get("description") or reason.get("type")
            self.kv("Redacted Fields", f"{text(name)} ({self.tr('Reason')}: {text(reason)})", indent)

    def display(self, data, indent=0, url="", depth=0):
        if depth > 16:
            self.kv("Notice", "Profondeur maximale des objets imbriques atteinte.", indent)
            return
        kind = data.get("objectClassName")
        classes = {"domain": "Domain Name", "ip network": "IP Network", "autnum": "Autonomous System", "entity": "Entity", "nameserver": "Nameserver", "help": "Help"}
        if kind is None and urlsplit(url).path.rstrip("/").endswith("/help"):
            kind = "help"
        if kind is None:
            raise RdapError("La reponse ne contient pas objectClassName; utiliser --raw pour afficher le JSON.")
        if not isinstance(kind, str):
            raise RdapError("objectClassName doit etre une chaine de caracteres.")
        if indent == 0:
            self.kv("Object type", self.tr(classes.get(kind, text(kind))))
            own = next((link.get("href") for link in objects(data.get("links")) if link.get("rel") == "self"), url)
            if own:
                self.kv("URL", own)
        name = data.get("ldhName") or data.get("name")
        if name:
            unicode_name = data.get("unicodeName")
            self.kv("Name", f"{unicode_name} ({name})" if unicode_name and unicode_name != name else name, indent)
        if data.get("handle") and not (kind == "entity" and indent):
            self.kv("Handle", data["handle"], indent)
        if kind == "domain":
            for ns in sorted(objects(data.get("nameservers")), key=lambda n: text(n.get("ldhName")).lower()):
                self.kv("Nameserver", ns.get("unicodeName") or ns.get("ldhName", ""), indent)
                self.nameserver(ns, indent + 1)
            secure = data.get("secureDNS")
            if isinstance(secure, dict):
                for key, label in (("zoneSigned", "DNSSEC signed"), ("delegationSigned", "DNSSEC delegation signed")):
                    if key in secure:
                        self.kv(label, self.tr("yes" if secure[key] else "no"), indent)
                for field, label, keys in (("dsData", "DS Record", ("keyTag", "algorithm", "digestType", "digest")), ("keyData", "DNSKEY Record", ("flags", "protocol", "algorithm", "publicKey"))):
                    for record in objects(secure.get(field)):
                        self.kv(label, " ".join(text(record.get(key)) for key in keys), indent)
            for record in objects(data.get("artRecord_record")):
                self.kv(record.get("name") or "Art Record", record.get("value"), indent)
            for ns in objects(data.get("platformNS_nameservers")):
                self.kv("Platform Nameserver", ns.get("ldhName"), indent)
            if data.get("regType_regType"):
                self.kv("Registration Type", data["regType_regType"], indent)
            self.ttl(data, indent)
        elif kind == "ip network":
            for field, label in (("ipVersion", "Version"), ("type", "Type"), ("country", "Country"), ("parentHandle", "Parent")):
                if data.get(field):
                    self.kv(label, data[field], indent)
            if data.get("startAddress") or data.get("endAddress"):
                self.kv("Range", f"{data.get('startAddress', '')} - {data.get('endAddress', '')}", indent)
            for cidr in objects(data.get("cidr0_cidrs")):
                self.kv("CIDR", f"{cidr.get('v4prefix') or cidr.get('v6prefix', '')}/{cidr.get('length', '')}", indent)
        elif kind == "autnum":
            if "startAutnum" in data:
                self.kv("Range", f"AS{data['startAutnum']} - AS{data.get('endAutnum', data['startAutnum'])}", indent)
            if data.get("type"):
                self.kv("Type", data["type"], indent)
        elif kind == "nameserver":
            self.nameserver({key: val for key, val in data.items() if key != "handle"}, indent)
        if kind == "entity":
            for public_id in objects(data.get("publicIds")):
                self.kv(public_id.get("type") or "ID", public_id.get("identifier"), indent)
            self.vcard(data, indent)
        for event in objects(data.get("events")) + objects(data.get("asEventActor")):
            action = text(event.get("eventAction", "Event")).capitalize()
            if action.lower() == "last update of rdap database":
                action = "Last update of RDAP database"
            value = text(event.get("eventDate"))
            if event.get("eventActor"):
                value += " (" + text(event["eventActor"]) + ")"
            self.kv(action, value, indent)
        for status in items(data.get("status")):
            value = text(status)
            if kind == "domain" and not self.short:
                words = value.split()
                epp = words[0] + "".join(word.capitalize() for word in words[1:]) if words else ""
                epp = {"active": "ok", "associated": "linked"}.get(value, epp if epp in EPP_STATUSES else "")
                if epp:
                    value += f" (https://icann.org/epp#{epp})"
            self.kv("Status", value, indent)
        order = ("registrant", "administrative", "technical", "billing", "abuse", "registrar", "reseller", "sponsor", "proxy", "notifications", "noc")
        for entity in sorted(objects(data.get("entities")), key=lambda e: min((order.index(role) for role in items(e.get("roles")) if role in order), default=len(order))):
            roles = ", ".join(self.tr(text(role).capitalize()) for role in items(entity.get("roles")))
            label = "Contact" + (" " + roles if roles else "") if self.fr else (roles + " " if roles else "") + "Contact"
            self.kv(label, entity.get("handle", ""), indent)
            self.display(dict(entity, objectClassName="entity"), indent + 1, depth=depth + 1)
        if not self.short:
            self.extras(data, indent)

    def render(self, response):
        self.lines = []
        self.display(response.data, url=response.url)
        return "\n".join(self.lines)


def preferred_language():
    try:
        value = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or locale.getlocale()[0] or "en"
    except (ValueError, TypeError):
        value = "en"
    value = value.split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    if value.lower().startswith("french"):
        return "fr"
    return value if re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value) else "en"


def positive_timeout(value):
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("Le delai doit etre un nombre positif fini.") from None


def parser():
    p = argparse.ArgumentParser(prog="rdappy", description="Client RDAP en un seul fichier Python, sans dependance externe.", epilog="Exemples : python rdappy.py example.com | --raw 1.1.1.1 | AS13335 | --search \"exampl*.com\".", allow_abbrev=False)
    p.add_argument("query", nargs="?", metavar="OBJET", help="domaine, IP/CIDR, ASN, handle avec tag, TLD ou URL RDAP")
    p.add_argument("--object", dest="named_query", metavar="OBJET", help="autre syntaxe pour fournir l'objet")
    p.add_argument("--type", choices=TYPES, dest="kind", help="imposer le type d'objet")
    for kind in TYPES:
        p.add_argument("--" + kind, dest="kind", action="store_const", const=kind, help=f"alias de --type={kind}")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--registry", dest="mode", action="store_const", const="registry", help="reponse du registre uniquement")
    mode.add_argument("--registrar", dest="mode", action="store_const", const="registrar", help="suivre le renvoi registrar (par defaut)")
    mode.add_argument("--both", dest="mode", action="store_const", const="both", help="reponses du registre et du registrar")
    p.set_defaults(mode="registrar")
    p.add_argument("--raw", "--json", action="store_true", help="afficher le JSON complet")
    p.add_argument("--short", action="store_true", help="omettre liens, remarques, avis et champs masques")
    p.add_argument("--search", action="store_true", help="rechercher des domaines (sans suffixe : tous les serveurs IANA)")
    p.add_argument("--reverse", action="store_true", help="pour une IP, interroger la zone inverse du bloc attribue")
    p.add_argument("--server", metavar="URL", help="URL de base du serveur RDAP a interroger")
    p.add_argument("--auth", metavar="USER:PASS", help="HTTP Basic, limite a l'origine du premier serveur interroge")
    p.add_argument("--timeout", type=positive_timeout, default=20, metavar="SECONDES", help="delai reseau par requete (defaut : 20)")
    p.add_argument("--cache-dir", metavar="DOSSIER", help="activer le cache disque (300 s; bootstrap IANA : 24 h)")
    p.add_argument("--bypass-cache", action="store_true", help="ignorer les caches et ne pas y ecrire")
    p.add_argument("--file", metavar="JSON", help="lire un JSON local, sans requete reseau")
    p.add_argument("--language", default=preferred_language(), metavar="LANGUE", help="Accept-Language et affichage fr/en (defaut : langue du systeme)")
    p.add_argument("--nocolor", "--no-color", action="store_true", help="desactiver les couleurs ANSI")
    p.add_argument("--nopager", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--insecure", action="store_true", help="desactiver la verification des certificats TLS")
    p.add_argument("--debug", action="store_true", help="afficher les URL interrogees sur stderr")
    config = p.add_mutually_exclusive_group()
    config.add_argument("--config", metavar="FICHIER", help="configuration, un argument par ligne (defaut : ~/.rdappy, puis ~/.rdapper)")
    config.add_argument("--no-config", action="store_true", help="ignorer la configuration")
    p.add_argument("--license", action="store_true", help="afficher la licence incluse dans ce fichier")
    p.add_argument("--version", action="version", version=f"rdappy {VERSION}")
    return p


def configuration_args(argv):
    if "--no-config" in argv or any(flag in argv for flag in ("--help", "-h", "--version", "--license")):
        return argv
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--config")
    options, _ = pre.parse_known_args(argv)
    path = Path(options.config).expanduser() if options.config else Path.home() / ".rdappy"
    if not options.config and not path.is_file():
        path = Path.home() / ".rdapper"
    try:
        with path.open(encoding="utf-8-sig") as stream:
            lines = stream.read(65537)
    except FileNotFoundError:
        if options.config:
            raise RdapError(f"Configuration introuvable : {path}") from None
        return argv
    except (OSError, UnicodeError) as exc:
        raise RdapError(f"Configuration illisible : {path} : {exc}") from None
    if len(lines) > 65536:
        raise RdapError("La configuration depasse 64 Kio.")
    # Comme rdapper: arguments ajoutes apres la ligne de commande, un par ligne.
    return argv + [line.strip() for line in lines.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        p = parser()
        args = p.parse_args(configuration_args(argv))
        if args.license:
            print(ARTISTIC_LICENSE)
            return 0
        if args.query and args.named_query:
            p.error("Fournir OBJET ou --object, un seul a la fois.")
        value = args.query or args.named_query
        if args.file and (value or args.search or args.reverse):
            p.error("--file attend uniquement un fichier JSON local.")
        if not value and not args.file:
            p.error("Fournir un objet RDAP, ou utiliser --help.")
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", args.language):
            p.error("--language attend une balise comme fr, en ou fr-FR.")
        if args.auth and (":" not in args.auth or ":" == args.auth or any(c in args.auth for c in "\r\n")):
            p.error("--auth attend USER:PASS.")
        if args.auth and not (args.server or (value and (args.kind == "url" or detect_type(value) == "url"))):
            p.error("--auth exige --server URL ou une URL RDAP explicite.")
        if args.file and (args.auth or args.server):
            p.error("--file ne peut pas etre combine avec --auth ou --server.")
        kind = args.kind or (detect_type(value) if value else None)
        if args.search and args.kind not in (None, "domain"):
            p.error("--search est disponible pour les domaines uniquement.")
        if args.reverse and (kind != "ip" or args.search):
            p.error("--reverse attend une adresse IP ou un prefixe CIDR.")
        if args.insecure:
            print("Avertissement : verification des certificats TLS desactivee.", file=sys.stderr)
        client = Client(timeout=args.timeout, cache_dir=args.cache_dir, bypass=args.bypass_cache, auth=args.auth, language=args.language, debug=args.debug, insecure=args.insecure)
        if args.file:
            responses = [local_document(args.file)]
        elif args.search:
            responses = client.search(value, server=args.server)
        else:
            responses = client.records(client.lookup(value, kind, server=args.server, reverse=args.reverse), args.mode)
        if args.raw:
            payload = responses[0].data if len(responses) == 1 else [response.data for response in responses]
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        elif args.search or any(any(key in response.data for key in SEARCH_KEYS) for response in responses):
            seen = set()
            for response in responses:
                for key in SEARCH_KEYS:
                    for entry in objects(response.data.get(key)):
                        name = text(entry.get("unicodeName") or entry.get("ldhName") or entry.get("handle"))
                        if name and name.lower() not in seen:
                            print(terminal_text(name))
                            seen.add(name.lower())
                if not args.short:
                    for notice in objects(response.data.get("notices")):
                        print("Avis : " + terminal_text(notice.get("title")) + " : " + terminal_text(notice.get("description")), file=sys.stderr)
        else:
            formatter = Formatter(short=args.short, color=sys.stdout.isatty() and not args.nocolor and "NO_COLOR" not in os.environ, language=args.language)
            for response in responses:
                print(formatter.render(response))
                if len(responses) > 1:
                    print()
        return 0
    except RdapError as exc:
        print("Erreur : " + terminal_text(exc), file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return 130




ARTISTIC_LICENSE = """rdappy — Python port of App::rdapper 1.26
Original: Copyright (c) 2012-2023 CentralNic Ltd.; 2023-2026 Gavin Brown.
Python rewrite: 2026-10-28. Original source: https://github.com/gbxyz/rdapper/tree/b168358d9513d0b170c8e2c190c845e8ee5ef1fa

The "Artistic License"

                                Preamble

The intent of this document is to state the conditions under which a
Package may be copied, such that the Copyright Holder maintains some
semblance of artistic control over the development of the package,
while giving the users of the package the right to use and distribute
the Package in a more-or-less customary fashion, plus the right to make
reasonable modifications.

Definitions:

        "Package" refers to the collection of files distributed by the
        Copyright Holder, and derivatives of that collection of files
        created through textual modification.

        "Standard Version" refers to such a Package if it has not been
        modified, or has been modified in accordance with the wishes
        of the Copyright Holder as specified below.

        "Copyright Holder" is whoever is named in the copyright or
        copyrights for the package.

        "You" is you, if you're thinking about copying or distributing
        this Package.

        "Reasonable copying fee" is whatever you can justify on the
        basis of media cost, duplication charges, time of people involved,
        and so on.  (You will not be required to justify it to the
        Copyright Holder, but only to the computing community at large
        as a market that must bear the fee.)

        "Freely Available" means that no fee is charged for the item
        itself, though there may be fees involved in handling the item.
        It also means that recipients of the item may redistribute it
        under the same conditions they received it.

1. You may make and give away verbatim copies of the source form of the
Standard Version of this Package without restriction, provided that you
duplicate all of the original copyright notices and associated disclaimers.

2. You may apply bug fixes, portability fixes and other modifications
derived from the Public Domain or from the Copyright Holder.  A Package
modified in such a way shall still be considered the Standard Version.

3. You may otherwise modify your copy of this Package in any way, provided
that you insert a prominent notice in each changed file stating how and
when you changed that file, and provided that you do at least ONE of the
following:

    a) place your modifications in the Public Domain or otherwise make them
    Freely Available, such as by posting said modifications to Usenet or
    an equivalent medium, or placing the modifications on a major archive
    site such as uunet.uu.net, or by allowing the Copyright Holder to include
    your modifications in the Standard Version of the Package.

    b) use the modified Package only within your corporation or organization.

    c) rename any non-standard executables so the names do not conflict
    with standard executables, which must also be provided, and provide
    a separate manual page for each non-standard executable that clearly
    documents how it differs from the Standard Version.

    d) make other distribution arrangements with the Copyright Holder.

4. You may distribute the programs of this Package in object code or
executable form, provided that you do at least ONE of the following:

    a) distribute a Standard Version of the executables and library files,
    together with instructions (in the manual page or equivalent) on where
    to get the Standard Version.

    b) accompany the distribution with the machine-readable source of
    the Package with your modifications.

    c) give non-standard executables non-standard names, and clearly
    document the differences in manual pages (or equivalent), together
    with instructions on where to get the Standard Version.

    d) make other distribution arrangements with the Copyright Holder.

5. You may charge a reasonable copying fee for any distribution of this
Package.  You may charge any fee you choose for support of this
Package.  You may not charge a fee for this Package itself.  However,
you may distribute this Package in aggregate with other (possibly
commercial) programs as part of a larger (possibly commercial) software
distribution provided that you do not advertise this Package as a
product of your own.  You may embed this Package's interpreter within
an executable of yours (by linking); this shall be construed as a mere
form of aggregation, provided that the complete Standard Version of the
interpreter is so embedded.

6. The scripts and library files supplied as input to or produced as
output from the programs of this Package do not automatically fall
under the copyright of this Package, but belong to whoever generated
them, and may be sold commercially, and may be aggregated with this
Package.  If such scripts or library files are aggregated with this
Package via the so-called "undump" or "unexec" methods of producing a
binary executable image, then distribution of such an image shall
neither be construed as a distribution of this Package nor shall it
fall under the restrictions of Paragraphs 3 and 4, provided that you do
not represent such an executable image as a Standard Version of this
Package.

7. C subroutines (or comparably compiled subroutines in other
languages) supplied by you and linked into this Package in order to
emulate subroutines and variables of the language defined by this
Package shall not be considered part of this Package, but are the
equivalent of input as in Paragraph 6, provided these subroutines do
not change the language in any way that would cause it to fail the
regression tests for the language.

8. Aggregation of this Package with a commercial distribution is always
permitted provided that the use of this Package is embedded; that is,
when no overt attempt is made to make this Package's interfaces visible
to the end user of the commercial distribution.  Such use shall not be
construed as a distribution of this Package.

9. The name of the Copyright Holder may not be used to endorse or promote
products derived from this software without specific prior written permission.

10. THIS PACKAGE IS PROVIDED "AS IS" AND WITHOUT ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, WITHOUT LIMITATION, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

                                The End"""


def closed_output_pipe(error):
    if isinstance(error, BrokenPipeError):
        return True
    if os.name == "nt" and error.errno == errno.EINVAL:
        try:
            return stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode)
        except (OSError, ValueError):
            return False
    return False


def cli():
    """Console entry point with UTF-8 output and quiet pipeline termination."""
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8", errors="replace")
    try:
        result = main()
        sys.stdout.flush()
        return result
    except OSError as error:
        if not closed_output_pipe(error):
            raise
        # Prevent a second error when the interpreter flushes at shutdown.
        try:
            descriptor = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(descriptor, sys.stdout.fileno())
            finally:
                os.close(descriptor)
        except (OSError, ValueError):
            pass
        return 0


if __name__ == "__main__":
    sys.exit(cli())
