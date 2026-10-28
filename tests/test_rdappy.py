"""Offline integration tests for rdappy using a loopback HTTP server."""

import contextlib
import hashlib
import io
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, Request

from rdappy import (
    Client, Formatter, RdapError, Response, as_number, configuration_args,
    decode_document, detect_type, domain_name, http_url, ip_network,
    local_document, main, origin, owner_summary, parser, reverse_name, reverse_network,
)
import rdappy

domain = {"objectClassName": "domain", "ldhName": "example.test", "handle": "REGISTRY", "entities": [{"objectClassName": "entity", "handle": "E-TEST", "roles": ["registrant"], "vcardArray": ["vcard", [["fn", {}, "text", "Alice"], ["email", {}, "text", "alice@example.test"], ["adr", {}, "text", ["", "", "1 Test Street", "Paris", "", "75000", "FR"]]]]}], "secureDNS": {"delegationSigned": True, "dsData": [{"keyTag": 1, "algorithm": 13, "digestType": 2, "digest": "ABCD"}]}, "notices": [{"title": "Terms", "description": ["Notice text"]}]}

requests = []
base = ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        requests.append((self.path, self.headers.get("Authorization"), self.headers.get("Accept-Language")))
        status, headers = 200, {}
        if self.path == "/redirect":
            status, headers = 302, {"Location": "/registry/domain/example.test"}
            body = {}
        elif self.path == "/cross-redirect":
            status, headers = 302, {"Location": base.replace("127.0.0.1", "localhost") + "registry/domain/example.test"}
            body = {}
        elif self.path == "/bad-json":
            body = b"<html>not RDAP</html>"
        elif self.path == "/list-json":
            body = []
        elif self.path == "/missing":
            status, body = 404, {"errorCode": 404, "title": "Not Found"}
        elif self.path == "/limited":
            status, body, headers = 429, {"errorCode": 429, "title": "Too Many Requests"}, {"Retry-After": "30"}
        elif self.path == "/no-store":
            body, headers = domain, {"Cache-Control": "no-store"}
        elif self.path.startswith("/registry/domains?"):
            body = {"domainSearchResult" if "nic.test" in self.path else "domainSearchResults": [domain]}
        elif self.path == "/registry/ip/1.1.1.1":
            body = {"objectClassName": "ip network", "startAddress": "1.1.1.0", "endAddress": "1.1.1.255"}
        elif self.path == "/registry/domain/1.1.1.in-addr.arpa":
            body = {"objectClassName": "domain", "ldhName": "1.1.1.in-addr.arpa"}
        elif self.path.startswith("/registrar/"):
            body = dict(domain, handle="REGISTRAR")
        elif self.path == "/registry/domain/example.test":
            body = dict(domain, links=[{"rel": "related", "type": "application/rdap+json", "href": base + "registrar/domain/example.test"}])
        else:
            status, body = 404, {"errorCode": 404, "title": "Not Found"}
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/rdap+json")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)



class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global base
        cls.environment = patch.dict(os.environ, {"no_proxy": "127.0.0.1,localhost", "NO_PROXY": "127.0.0.1,localhost"})
        cls.environment.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{cls.server.server_port}/"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.environment.stop()

    def setUp(self):
        requests.clear()
        self.client = Client(bypass=True, timeout=3)
        self.client.opener.add_handler(ProxyHandler({}))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--no-config", *args])
        return code, out.getvalue(), err.getvalue()

    def test_detection_and_validation(self):
        for value, kind in (("example.com", "domain"), ("com", "tld"), ("AS13335", "autnum"), ("ASN42", "autnum"), ("42", "autnum"), ("1.1.1.1", "ip"), ("::ffff:192.0.2.1", "ip"), (base, "url")):
            self.assertEqual(detect_type(value), kind)
        self.assertEqual(domain_name("B\u00dcCHER.de."), "xn--bcher-kva.de")
        self.assertEqual(domain_name("xn--fa-hia.de"), "xn--fa-hia.de")
        self.assertEqual(str(ip_network("1.1.1.7/24")), "1.1.1.0/24")
        self.assertEqual(as_number("AS4294967295"), 4294967295)
        for bad in ("-x.test", "a..test", "a/b.test", "a b.test", "xn--.test"):
            with self.assertRaises(RdapError):
                domain_name(bad)
        with self.assertRaises(RdapError):
            ip_network("999.1.1.1")
        with self.assertRaises(RdapError):
            as_number("4294967296")

    def test_reverse_domains(self):
        for name, prefix in (("0.10.in-addr.arpa", "10.0.0.0/16"), ("8.8.8.8.in-addr.arpa", "8.8.8.8/32"), ("8.b.d.0.1.0.0.2.ip6.arpa", "2001:db8::/32")):
            self.assertEqual(str(reverse_network(name)), prefix)
            self.assertEqual(reverse_name(ip_network(prefix)), name)
        with self.assertRaises(RdapError):
            reverse_network("999.in-addr.arpa")
        result = self.client.lookup("1.1.1.1", server=base + "registry/", reverse=True)
        self.assertEqual(result.data["ldhName"], "1.1.1.in-addr.arpa")

    def test_bootstrap_specificity(self):
        fixtures = {
            "dns": {"services": [[["test"], ["http://root.test/", "https://root.test/"]], [["sub.test"], ["https://sub.test/"]]]},
            "ipv4": {"services": [[["0.0.0.0/0"], ["https://all.test/"]], [["1.1.0.0/16"], ["https://ip.test/"]]]},
            "ipv6": {"services": [[["2001::/16"], ["https://v6.test/"]]]},
            "asn": {"services": [[["1-100"], ["https://all.test/"]], [["42"], ["https://as.test/"]]]},
            "object-tags": {"services": [[["contact@example.test"], ["TEST"], ["https://entity.test/"]]]},
        }
        def fake_fetch(url, **kwargs):
            return Response(fixtures[url.rsplit("/", 1)[-1][:-5]], url)
        with patch.object(self.client, "fetch", side_effect=fake_fetch):
            self.assertEqual(self.client.bases("domain", "a.sub.test"), ["https://sub.test/"])
            self.assertEqual(self.client.bases("nameserver", "ns.test")[0], "https://root.test/")
            self.assertEqual(self.client.bases("ip", "1.1.1.1"), ["https://ip.test/"])
            self.assertEqual(self.client.bases("ip", "2001:db8::1"), ["https://v6.test/"])
            self.assertEqual(self.client.bases("autnum", "AS42"), ["https://as.test/"])
            self.assertEqual(self.client.bases("entity", "ABC-test"), ["https://entity.test/"])
            with self.assertRaises(RdapError):
                self.client.bases("entity", "ABC-UNKNOWN")

    def test_lookup_and_referrals(self):
        response = self.client.lookup("example.test", server=base + "registry/")
        self.assertEqual(self.client.records(response, "registry")[0].data["handle"], "REGISTRY")
        self.assertEqual(self.client.records(response)[0].data["handle"], "REGISTRAR")
        self.assertEqual([r.data["handle"] for r in self.client.records(response, "both")], ["REGISTRY", "REGISTRAR"])
        broken = Response(dict(domain, links=[{"rel": "related", "type": "application/rdap+json", "href": base + "missing"}]), response.url)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.client.records(broken), [broken])
        self.assertIn("displaying the registry record", err.getvalue())

    def test_http_errors_and_invalid_json(self):
        for path, status in (("missing", 404), ("limited", 429), ("bad-json", None), ("list-json", None)):
            with self.assertRaises(RdapError) as error:
                self.client.fetch(base + path)
            self.assertEqual(error.exception.status, status)
        with self.assertRaises(RdapError):
            decode_document(b'{"errorCode":403,"title":"Forbidden"}', base)
        with patch.object(self.client.opener, "open", side_effect=HTTPException("connection interrupted")):
            with self.assertRaises(RdapError):
                self.client.fetch(base + "truncated")

    def test_failover_and_rate_limits(self):
        response = Response(domain, base)
        with patch.object(self.client, "fetch", side_effect=[RdapError("connection failed"), response]) as fetch:
            self.assertEqual(self.client.candidates([base + "first", base + "second"]), response)
            self.assertEqual(fetch.call_count, 2)
        with patch.object(self.client, "fetch", side_effect=RdapError("rate limit reached", 429)) as fetch:
            with self.assertRaises(RdapError):
                self.client.candidates([base + "first", base + "second"])
            self.assertEqual(fetch.call_count, 1)

    def test_auth_and_redirects(self):
        client = Client(auth="user:pass", bypass=True, timeout=3, language="fr")
        client.fetch(base + "redirect", authenticated=True)
        self.assertTrue(all(auth for _, auth, _ in requests))
        self.assertTrue(all(language == "fr" for _, _, language in requests))
        requests.clear()
        client.fetch(base + "cross-redirect", authenticated=True)
        self.assertIsNotNone(requests[0][1])
        self.assertIsNone(requests[-1][1])
        client.fetch(base + "registry/domain/example.test")
        self.assertIsNone(requests[-1][1])
        with self.assertRaises(RdapError):
            http_url("file:///etc/passwd")
        with self.assertRaises(RdapError):
            http_url("https://user:pass@example.test/")

    def test_cache(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
            client = Client(cache_dir=directory, timeout=3)
            client.fetch(base + "registry/domain/example.test")
            client.fetch(base + "registry/domain/example.test")
            self.assertEqual(len(requests), 1)
            Client(cache_dir=directory, timeout=3).fetch(base + "registry/domain/example.test")
            self.assertEqual(len(requests), 1)
            Client(cache_dir=directory, bypass=True, timeout=3).fetch(base + "registry/domain/example.test")
            self.assertEqual(len(requests), 2)
            client.fetch(base + "no-store")
            client.fetch(base + "no-store")
            self.assertEqual(len(requests), 4)
            client.memory[base + "registry/domain/example.test"]["expires"] = 0
            client.fetch(base + "registry/domain/example.test")
            self.assertEqual(len(requests), 5)

    def test_search_and_json_output(self):
        code, out, err = self.run_cli("--server", base + "registry/", "--search", "exampl*.test")
        self.assertEqual((code, out.strip(), err), (0, "example.test", ""))
        self.assertIn("name=exampl%2A.test", requests[-1][0])
        code, out, err = self.run_cli("--server", base + "registry/", "--search", "nic.test")
        self.assertEqual((code, out.strip(), err), (0, "example.test", ""))
        code, out, err = self.run_cli("--server", base + "registry/", "--search", "--raw", "nic.test")
        self.assertEqual(code, 0, err)
        self.assertIn("domainSearchResult", json.loads(out))
        self.assertNotIn("domainSearchResults", json.loads(out))
        code, out, err = self.run_cli("--server", base + "registry/", "--both", "--raw", "example.test")
        self.assertEqual(code, 0, err)
        self.assertEqual([record["handle"] for record in json.loads(out)], ["REGISTRY", "REGISTRAR"])
        code, out, err = self.run_cli(base + "missing")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("404", err)

    def test_formatting(self):
        response = Response(domain, base)
        output = Formatter(width=120).render(response)
        for value in ("Alice", "alice@example.test", "Paris", "DS Record: 1 13 2 ABCD", "Notice text"):
            self.assertIn(value, output)
        short = Formatter(short=True).render(response)
        self.assertNotIn("Notice text", short)
        self.assertIn("Alice", short)
        self.assertIn("Object type: Domain Name", Formatter().render(response))
        self.assertNotIn("\x1b", Formatter().render(Response(dict(domain, ldhName="x\x1b[2J"), base)))
        enriched = dict(domain, status=["active", "associated", "validated"], ttl0_data={"values": {"NS": 3600}, "remarks": [{"description": ["TTL notice"]}]})
        output = Formatter().render(Response(enriched, base))
        self.assertIn("https://icann.org/epp#ok", output)
        self.assertIn("https://icann.org/epp#linked", output)
        self.assertNotIn("https://icann.org/epp#validated", output)
        self.assertIn("NS: 3600 s", output)
        self.assertIn("TTL notice", output)
        self.assertNotIn("TTL notice", Formatter(short=True).render(Response(enriched, base)))
        with self.assertRaises(RdapError):
            Formatter().render(Response({"objectClassName": []}, base))

    def test_local_file_and_configuration(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(domain), encoding="utf-8")
            code, out, err = self.run_cli("--file", str(path), "--raw")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), domain)
            self.assertEqual(local_document(path.as_uri()).data, domain)
            self.assertEqual(requests, [])
            config = Path(directory) / "config"
            config.write_text("# comment\n--short\n--language=fr\n", encoding="utf-8")
            args = parser().parse_args(configuration_args(["--config", str(config), "example.test"]))
            self.assertTrue(args.short)
            self.assertEqual(args.language, "fr")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(["--no-config", "--registry", "--both", "example.test"])
            self.assertEqual(error.exception.code, 2)

    def test_strict_json_numbers(self):
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e9999}'):
            with self.subTest(raw=raw), self.assertRaises(RdapError):
                decode_document(raw, base)
        self.assertEqual(decode_document(b'{"x":0.25,"y":null}', base).data, {"x": 0.25, "y": None})

    def test_url_validation_and_tls_downgrade(self):
        for value in (None, "http://example.test:invalid/", "https://example.test\\path", "https://example.test/\n", "ftp://example.test/"):
            with self.subTest(value=value), self.assertRaises(RdapError):
                http_url(value)
        self.assertNotEqual(origin("https://example.test:0/"), origin("https://example.test/"))
        request = Request("https://example.test/")
        with self.assertRaises(RdapError):
            rdappy.SafeRedirect().redirect_request(request, None, 302, "Found", {}, "http://example.test/")

    def test_only_domains_follow_registrar_referrals(self):
        data = {"objectClassName": "ip network", "links": [{"rel": "related", "type": "application/rdap+json", "href": base + "registrar/domain/example.test"}]}
        response = Response(data, base + "registry/ip/1.1.1.1")
        with patch.object(self.client, "fetch") as fetch:
            self.assertEqual(self.client.records(response), [response])
            fetch.assert_not_called()
        domain_response = Response(dict(domain, links=[{"rel": "related", "type": "application/rdap+json", "href": base + "registry/ip/1.1.1.1"}]), base)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.client.records(domain_response), [domain_response])

    def test_corrupt_cache_is_ignored(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
            url = base + "registry/domain/example.test"
            path = Path(directory) / (hashlib.sha256(url.encode()).hexdigest() + ".json")
            for content in ("invalid JSON", '{"url":"wrong"}', json.dumps({"url": url, "expires": 10 ** 100, "data": domain}), json.dumps({"url": url, "expires": 9999999999, "data": domain, "final_url": 123})):
                path.write_text(content, encoding="utf-8")
                client = Client(cache_dir=directory, timeout=3)
                self.assertIsNone(client.cache_read(url))
            client.fetch(url)
            self.assertEqual(len(requests), 1)

    def test_response_size_limit(self):
        with patch.object(rdappy, "MAX_BYTES", 8):
            with self.assertRaises(RdapError):
                self.client.fetch(base + "registry/domain/example.test")
            with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
                path = Path(directory) / "large.json"
                path.write_text(json.dumps(domain), encoding="utf-8")
                with self.assertRaises(RdapError):
                    local_document(str(path))

    def test_cli_rejects_invalid_combinations(self):
        cases = (["--timeout", "nan", "example.test"], ["--timeout", "0", "example.test"], ["--reverse", "example.test"], ["--search", "--entity", "ABC-TEST"], ["--auth", "user:pass", "example.test"], ["--file", "x.json", "--server", base], ["--language", "fr\nX: y", "example.test"], ["--object", "a.test", "b.test"])
        for args in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--no-config", *args])
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(requests, [])

    def test_config_prefers_rdappy_then_legacy(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
            home = Path(directory)
            (home / ".rdapper").write_text("--language=en\n", encoding="utf-8")
            (home / ".rdappy").write_text("--language=fr\n", encoding="utf-8")
            with patch.object(Path, "home", return_value=home):
                self.assertEqual(parser().parse_args(configuration_args(["example.test"])).language, "fr")
                (home / ".rdappy").unlink()
                self.assertEqual(parser().parse_args(configuration_args(["example.test"])).language, "en")
                self.assertEqual(configuration_args(["--no-config", "example.test"]), ["--no-config", "example.test"])

    def test_empty_search_is_success(self):
        with patch.object(Client, "search", return_value=[Response({"domainSearchResults": []}, base)]):
            self.assertEqual(self.run_cli("--search", "absent.test"), (0, "", ""))

    def test_owner_summary_uses_only_direct_registrants(self):
        owner = {"roles": ["registrant"], "vcardArray": ["vcard", [
            ["org", {}, "text", "Example Company"], ["fn", {}, "text", "Alice"],
            ["email", {}, "text", "owner@example.test"],
            ["adr", {"cc": "FR"}, "text", ["", "", "", "", "", "", "France"]],
        ]]}
        unrelated = {"roles": ["registrar"], "vcardArray": ["vcard", [["org", {}, "text", "Wrong Registrar"]]],
                     "entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [["org", {}, "text", "Nested Registrar Owner"]]]}]}
        data = dict(domain, entities=[owner, unrelated, {"roles": ["abuse"], "vcardArray": ["vcard", [["org", {}, "text", "Abuse Organization"]]]}])
        summary = owner_summary([Response(data, base)])
        self.assertEqual(summary["organizations"], ["Example Company"])
        self.assertEqual(summary["registrants"], ["Alice"])
        self.assertEqual(summary["emails"], ["owner@example.test"])
        self.assertEqual(summary["countries"], ["FR"])
        output = Formatter().render_owner(summary)
        self.assertIn("Organization: Example Company", output)
        self.assertNotIn("Wrong Registrar", output)
        self.assertNotIn("Nested Registrar Owner", output)
        self.assertNotIn("Abuse Organization", output)
        self.assertNotIn("Notice text", output)

    def test_owner_summary_rir_org_kind_and_individual_names(self):
        data = {"objectClassName": "ip network", "name": "NETWORK-LABEL", "country": "US",
                "startAddress": "192.0.2.0", "endAddress": "192.0.2.255",
                "entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [
                    ["kind", {}, "text", "org"], ["fn", {}, "text", "Example Operator"],
                ]]}]}
        summary = owner_summary([Response(data, base)])
        self.assertEqual(summary["organizations"], ["Example Operator"])
        self.assertEqual(summary["registrants"], [])
        self.assertEqual(summary["countries"], [])
        self.assertIn("Network: 192.0.2.0 - 192.0.2.255", Formatter().render_owner(summary))
        individual = {"roles": ["registrant"], "vcardArray": ["vcard", [["kind", {}, "text", "individual"], ["fn", {}, "text", "Alice"]]]}
        summary = owner_summary([Response(dict(data, entities=[individual]), base)])
        self.assertEqual(summary["organizations"], [])
        self.assertEqual(summary["registrants"], ["Alice"])

    def test_owner_summary_merges_sources_and_deduplicates(self):
        first = {"roles": ["registrant"], "vcardArray": ["vcard", [
            ["org", {}, "text", "Example Company"], ["fn", {}, "text", "Alice"],
            ["email", {}, "text", "owner@example.test"],
        ]]}
        second = {"roles": ["registrant"], "vcardArray": ["vcard", [
            ["org", {}, "text", "EXAMPLE COMPANY"], ["fn", {}, "text", "Alice"],
            ["email", {}, "text", "owner@example.test"], ["email", {}, "text", "public@example.test"],
        ]]}
        records = [Response(dict(domain, entities=[first]), base + "registry"),
                   Response(dict(domain, ldhName="EXAMPLE.TEST.", entities=[second]), base + "registrar")]
        summary = owner_summary(records)
        self.assertEqual(summary["organizations"], ["Example Company"])
        self.assertEqual(summary["registrants"], ["Alice"])
        self.assertEqual(summary["emails"], ["owner@example.test", "public@example.test"])
        self.assertEqual(summary["sources"], [base + "registry", base + "registrar"])

    def test_owner_summary_never_substitutes_registrar_for_missing_owner(self):
        registrar = {"roles": ["registrar"], "vcardArray": ["vcard", [["org", {}, "text", "Registrar Company"]]]}
        malformed = {"roles": ["registrant"], "vcardArray": ["vcard", None]}
        summary = owner_summary([Response(dict(domain, entities=[registrar, malformed]), base)])
        self.assertEqual(summary["organizations"], [])
        self.assertEqual(summary["registrants"], [])
        output = Formatter().render_owner(summary)
        self.assertIn("Organization: Not disclosed or not provided", output)
        self.assertNotIn("Registrar Company", output)

    def test_owner_cli_fetches_both_sources_unless_explicitly_selected(self):
        code, out, err = self.run_cli("--server", base + "registry/", "--owner", "--raw", "example.test")
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual(summary["object_type"], "domain")
        self.assertEqual(summary["registrants"], ["Alice"])
        self.assertEqual(len(summary["sources"]), 2)
        self.assertEqual(len(requests), 2)
        for mode in ("--registry", "--registrar"):
            requests.clear()
            code, out, err = self.run_cli("--server", base + "registry/", "--owner", mode, "--raw", "example.test")
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["sources"]), 1)
            self.assertEqual(len(requests), 1 if mode == "--registry" else 2)

    def test_owner_cli_local_json_is_focused_and_offline(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(domain), encoding="utf-8")
            code, out, err = self.run_cli("--owner", "--file", str(path), "--raw")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["registrants"], ["Alice"])
            self.assertNotIn("entities", json.loads(out))
            code, out, err = self.run_cli("--owner", "--file", str(path))
            self.assertEqual(code, 0, err)
            self.assertIn("Registrant: Alice", out)
            self.assertNotIn("Notice text", out)
            self.assertEqual(requests, [])

    def test_owner_summary_rejects_mismatched_or_unsupported_records(self):
        records = [Response(domain, base), Response(dict(domain, ldhName="different.test"), base + "different")]
        with self.assertRaisesRegex(RdapError, "different domain names"):
            owner_summary(records)
        for records in ([], [Response({"objectClassName": "nameserver"}, base)],
                        [Response(domain, base), Response({"objectClassName": "autnum"}, base)]):
            with self.subTest(records=records), self.assertRaises(RdapError):
                owner_summary(records)

    def test_owner_cli_rejects_search(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--no-config", "--owner", "--search", "exampl*.test"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(requests, [])

    def test_search_deduplicates_services_and_results(self):
        with patch.object(self.client, "services", return_value=[(["a"], [base + "registry/"]), (["b"], [base + "registry/"])]):
            self.assertEqual(len(self.client.search("exampl*")), 1)
            self.assertEqual(len(requests), 1)
        result = Response({"domainSearchResults": [domain, dict(domain, ldhName="EXAMPLE.TEST")]}, base)
        with patch.object(Client, "search", return_value=[result, result]):
            self.assertEqual(self.run_cli("--search", "example.test"), (0, "example.test\n", ""))

    def test_authentication_does_not_enter_cache_or_logs(self):
        out = io.StringIO()
        client = Client(auth="user:private-password", debug=True, timeout=3)
        with contextlib.redirect_stderr(out):
            client.fetch(base + "registry/domain/example.test", authenticated=True)
            client.fetch(base + "registry/domain/example.test", authenticated=True)
        self.assertEqual(client.memory, {})
        self.assertEqual(len(requests), 2)
        self.assertNotIn("private-password", out.getvalue())
        self.assertNotIn("Authorization", out.getvalue())

    def test_release_interface_has_no_embedded_test_runner(self):
        help_text = parser().format_help()
        self.assertNotIn("--self-test", help_text)
        self.assertNotIn("--source", help_text)
        self.assertEqual(parser().prog, "rdappy")

    def test_english_interface_is_independent_of_locale_and_response_language(self):
        with patch.dict(os.environ, {"LC_ALL": "fr_FR.UTF-8", "LC_MESSAGES": "fr_FR.UTF-8", "LANG": "fr_FR.UTF-8"}):
            self.assertEqual(parser().parse_args(["example.test"]).language, "en")
            self.assertIn("A single-file Python RDAP client", parser().format_help())
            code, out, err = self.run_cli("--registry", "--server", base + "registry/", "example.test")
            self.assertEqual(code, 0, err)
            self.assertIn("Object type: Domain Name", out)
            self.assertEqual(requests[-1][2], "en")
            code, out, err = self.run_cli("--registry", "--language", "fr", "--server", base + "registry/", "example.test")
            self.assertEqual(code, 0, err)
            self.assertIn("Object type: Domain Name", out)
            self.assertEqual(requests[-1][2], "fr")
            code, out, err = self.run_cli("--ip", "999.1.1.1")
            self.assertEqual((code, out), (1, ""))
            self.assertTrue(err.startswith("Error: Invalid IP address or prefix:"), err)

    def test_command_exits_cleanly_when_output_pipe_closes(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-test-", dir=Path(__file__).resolve().parent) as directory:
            sample = Path(directory) / "large.json"
            sample.write_text(json.dumps({"objectClassName": "domain", "ldhName": "example.test", "notices": [{"description": ["é" * 100000]}]}), encoding="utf-8")
            with subprocess.Popen([sys.executable, "-B", str(Path(rdappy.__file__).resolve()), "--no-config", "--file", str(sample), "--raw"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                process.stdout.close()
                code = process.wait(timeout=10)
                error = process.stderr.read().decode("utf-8")
            self.assertEqual(code, 0, error)
            self.assertNotIn("Traceback", error)



if __name__ == "__main__":
    unittest.main()
