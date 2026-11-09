"""Query coverage against an offline RDAP service, shared by both standalone files."""

import contextlib
import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import rdappy
from rdappy import Client, Formatter, RdapError, Response, detect_type, main


DOMAIN = {"objectClassName": "domain", "ldhName": "example.test"}
ENTITY = {"objectClassName": "entity", "handle": "MNT-ADSI", "vcardArray": ["vcard", [
    ["fn", {}, "text", "Example Maintainer"], ["kind", {}, "text", "individual"],
]], "entities": [{"handle": "CONTACT-RIPE", "roles": ["technical"], "links": [{
    "value": "https://rdap.db.ripe.net/entity/MNT-ADSI", "rel": "self",
    "href": "https://rdap.db.ripe.net/entity/CONTACT-RIPE",
}]}]}
NETWORK = {"objectClassName": "ip network", "startAddress": "192.0.2.0", "endAddress": "192.0.2.255"}
AUTNUM = {"objectClassName": "autnum", "startAutnum": 64496, "endAutnum": 64500}
NAMESERVER = {"objectClassName": "nameserver", "ldhName": "ns.example.test"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        parsed = urlsplit(self.path)
        root = parsed.path.removeprefix("/registry/").split("/", 1)[0]
        query = parse_qs(parsed.query)
        collections = {
            "domains": ("domainSearchResults", DOMAIN),
            "entities": ("entitySearchResults", ENTITY),
            "nameservers": ("nameserverSearchResults", NAMESERVER),
            "ips": ("ipSearchResults", NETWORK),
            "autnums": ("autnumSearchResults", AUTNUM),
        }
        if root in collections:
            key, record = collections[root]
            if query.get("response") == ["wrong"]:
                body = {"objectClassName": "domain"}
            else:
                if query.get("response") == ["singular"]:
                    key = key[:-1]
                body = {key: [] if query.get("response") == ["empty"] else [record], "vendor_extension": {"retained": True}}
        elif root == "arin_originas0_networksbyoriginas":
            body = ({"notices": [{"description": ["Terms for an empty extension response"]}]}
                    if query.get("response") == ["empty"] else
                    {"arin_originas0_networkSearchResults": [dict(NETWORK, handle="NET-192-0-2-0-1")]})
        elif root == "help":
            body = {"rdapConformance": ["rdap_level_0", "rirSearch1", "reverse_search"],
                    "notices": [{"title": "Supported queries", "description": ["Service help"]}]}
        else:
            body = {"domain": DOMAIN, "entity": ENTITY, "ip": NETWORK, "autnum": AUTNUM,
                    "nameserver": NAMESERVER}.get(root, {"objectClassName": "vendor_object", "handle": "CUSTOM"})
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rdap+json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(os.environ, {"no_proxy": "127.0.0.1,localhost", "NO_PROXY": "127.0.0.1,localhost"})
        cls.environment.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.requests = []
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/registry/"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.environment.stop()

    def setUp(self):
        self.server.requests.clear()
        self.client = Client(timeout=3, bypass=True)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--no-config", *args])
        return code, out.getvalue(), err.getvalue()

    def test_detects_entities_and_paths_without_changing_domains_ips_asns_or_tlds(self):
        cases = {
            "MNT-ADSI": "entity", "ADSI2-RIPE": "entity", "ORG-EXAMPLE-RIPE": "entity",
            "EXAMPLE-MNT": "entity", "ADMIN2521-ARIN": "entity", "IRT-EXAMPLE": "entity",
            "entity/MNT-ADSI": "path", "/entity/ADSI2-RIPE": "path",
            "ips/rirSearch1/rdap-up/192.0.2.0/24": "path", "entities?fn=Example*": "path",
            "domain/example.test": "path", "ip/2001:db8::/32": "path", "/help": "path", "/help?lang=fr": "path",
            "example-mnt.test": "domain", "help": "tld", "com": "tld",
            "192.0.2.0/24": "ip", "2001:db8::": "ip", "AS64496": "autnum",
        }
        for value, kind in cases.items():
            with self.subTest(value=value):
                self.assertEqual(detect_type(value), kind)

    def test_ripe_maintainer_organisation_and_tagged_contact_use_iana(self):
        services = [(["RIPE"], [self.base]), (["ARIN"], [self.base + "arin/"])]
        for handle in ("MNT-ADSI", "ORG-EXAMPLE", "EXAMPLE-MNT", "ADSI2-RIPE"):
            with self.subTest(handle=handle), patch.object(self.client, "services", return_value=services):
                response = self.client.lookup(handle)
                self.assertEqual(response.data["handle"], "MNT-ADSI")
                self.assertEqual(urlsplit(response.url).path, "/registry/entity/" + handle)
        with patch.object(self.client, "services", return_value=services):
            self.assertEqual(self.client.bases("entity", "ORG-EXAMPLE-ARIN"), [self.base + "arin/"])
            with self.assertRaises(RdapError):
                self.client.bases("entity", "UNREGISTERED-TAG")

    def test_relative_lookup_paths_discover_services_without_losing_query_parameters(self):
        for value, kind, lookup in (("/entity/MNT-ADSI?view=full", "entity", "MNT-ADSI"),
                                    ("ip/192.0.2.0/24", "ip", "192.0.2.0/24"),
                                    ("autnum/AS64496", "autnum", "64496"),
                                    ("domain/bücher.test", "domain", "xn--bcher-kva.test")):
            with self.subTest(value=value), patch.object(self.client, "bases", return_value=[self.base]) as bases:
                response = self.client.lookup(value)
                bases.assert_called_once_with(kind, lookup)
                self.assertTrue(response.url.startswith(self.base))
        self.assertIn("/registry/domain/b%C3%BCcher.test", self.server.requests[-1][0])
        self.assertIn("view=full", self.server.requests[0][0])

    def test_all_standard_search_fields_and_rir_collections(self):
        cases = (
            ("domain", "name", "exampl*.test", "domains", "example.test"),
            ("domain", "nsLdhName", "ns*.example.test", "domains", "example.test"),
            ("domain", "nsIp", "2001:db8::1", "domains", "example.test"),
            ("nameserver", "name", "ns*.example.test", "nameservers", "ns.example.test"),
            ("nameserver", "ip", "192.0.2.1", "nameservers", "ns.example.test"),
            ("entity", "fn", "Café & Fils*", "entities", "MNT-ADSI"),
            ("entity", "handle", "MNT-*", "entities", "MNT-ADSI"),
            ("ip", "name", "Example Network*", "ips", "192.0.2.0 - 192.0.2.255"),
            ("ip", "handle", "NET-192-*", "ips", "192.0.2.0 - 192.0.2.255"),
            ("autnum", "name", "EXAMPLE*", "autnums", "AS64496 - AS64500"),
            ("autnum", "handle", "AS644*", "autnums", "AS64496 - AS64500"),
        )
        for kind, field, pattern, collection, expected in cases:
            with self.subTest(kind=kind, field=field):
                code, out, err = self.run_cli("--server", self.base, "--search", "--type", kind,
                                               "--search-field", field, "--param", "limit=2", pattern)
                self.assertEqual((code, out.strip(), err), (0, expected, ""))
                parsed = urlsplit(self.server.requests[-1][0])
                self.assertEqual(parsed.path, "/registry/" + collection)
                self.assertEqual(parse_qs(parsed.query), {field: [pattern], "limit": ["2"]})

    def test_entity_names_are_normalized_and_encoded_without_dns_validation(self):
        result = self.client.search("Cafe\u0301 & Example / Europe*", kind="entity", server=self.base)
        self.assertEqual(result[0].data["entitySearchResults"][0]["handle"], "MNT-ADSI")
        query = urlsplit(self.server.requests[-1][0]).query
        self.assertEqual(parse_qs(query), {"fn": ["Café & Example / Europe*"]})
        self.assertNotIn("/ Europe", self.server.requests[-1][0])

    def test_search_empty_singular_and_raw_results_keep_existing_contract(self):
        for kind, key in (("entity", "entitySearchResults"), ("nameserver", "nameserverSearchResults"),
                          ("ip", "ipSearchResults"), ("autnum", "autnumSearchResults")):
            with self.subTest(kind=kind):
                args = ("--server", self.base, "--search", "--type", kind)
                self.assertEqual(self.run_cli(*args, "--param", "response=empty", "example*"), (0, "", ""))
                code, out, err = self.run_cli(*args, "--param", "response=singular", "--raw", "example*")
                self.assertEqual(code, 0, err)
                self.assertIn(key[:-1], json.loads(out))
                self.assertEqual(json.loads(out)["vendor_extension"], {"retained": True})
                code, out, err = self.run_cli(*args, "--param", "response=wrong", "example*")
                self.assertEqual((code, out), (1, ""))
                self.assertIn(key, err)

    def test_rir_relationships_reverse_search_and_vendor_paths_pass_through(self):
        queries = (
            "ips/rirSearch1/rdap-up/192.0.2.0/24?status=active",
            "autnums/rirSearch1/rdap-bottom/64496",
            "domains/rirSearch1/rdap-down/2.0.192.in-addr.arpa",
            "ips/reverse_search/entity?handle=MNT-ADSI&role=registrant",
            "autnums/reverse_search/entity?fn=Example%20Company*",
            "domains/reverse_search/entity?email=public%40example.test",
            "arin_originas0_networksbyoriginas/64496",
            "vendor/object/a%2Fb?feature=one&feature=two&empty=",
        )
        for query in queries:
            with self.subTest(query=query):
                code, out, err = self.run_cli("--server", self.base, "--path", "--raw", query)
                self.assertEqual(code, 0, err)
                self.assertIsInstance(json.loads(out), dict)
                self.assertEqual(self.server.requests[-1][0], "/registry/" + query)

    def test_namespaced_extension_search_results_work_in_text_and_raw_modes(self):
        args = ("--server", self.base, "--path", "arin_originas0_networksbyoriginas/64496")
        self.assertEqual(self.run_cli(*args), (0, "NET-192-0-2-0-1\n", ""))
        code, out, err = self.run_cli(*args, "--raw")
        self.assertEqual(code, 0, err)
        self.assertIn("arin_originas0_networkSearchResults", json.loads(out))
        self.assertEqual(rdappy.search_keys({"new_extension_objectSearchResults": []}), ["new_extension_objectSearchResults"])

    def test_notice_only_extension_responses_are_displayed_without_inventing_an_object(self):
        code, out, err = self.run_cli("--server", self.base, "--path",
                                       "arin_originas0_networksbyoriginas/64496?response=empty")
        self.assertEqual(code, 0, err)
        self.assertIn("Terms for an empty extension response", out)
        self.assertNotIn("AS64496 -", out)
        with self.assertRaises(RdapError):
            Formatter().render(Response({}, self.base + "vendor/invalid"))

    def test_unknown_or_search_paths_require_an_explicit_service(self):
        with patch.object(self.client, "fetch") as fetch:
            for path in ("entities?fn=Example*", "ips?name=Example*", "help", "vendor/foo"):
                with self.subTest(path=path), self.assertRaisesRegex(RdapError, "--server"):
                    self.client.query_path(path)
            fetch.assert_not_called()

    def test_server_base_is_retained_and_relative_paths_cannot_change_origin(self):
        for query in ("/entity/MNT-ADSI", "entity/MNT-ADSI"):
            self.client.query_path(query, server=self.base)
            self.assertEqual(self.server.requests[-1][0], "/registry/entity/MNT-ADSI")
        with patch.object(self.client, "fetch") as fetch:
            for value in ("//other.test/entity/X", "https://other.test/entity/X", "../entity/X",
                          "a/../../entity/X", "%2e%2e/entity/X", "a%2F..%2F../entity/X",
                          "entity/X#fragment", "entity/X\n", "entity/%0d%0aX", "entity\\X"):
                with self.subTest(value=value), self.assertRaises(RdapError):
                    self.client.query_path(value, server=self.base)
            fetch.assert_not_called()

    def test_rdap_help_is_distinct_from_local_help(self):
        for flag in (("--rdap-help",), ("--type", "help"), ("--path", "/help")):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli("--server", self.base, *flag)
                self.assertEqual(code, 0, err)
                self.assertIn("rirSearch1", out)
                self.assertIn("Service help", out)
                self.assertEqual(self.server.requests[-1][0], "/registry/help")
        before = len(self.server.requests)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--help"])
        self.assertEqual(error.exception.code, 0)
        self.assertEqual(len(self.server.requests), before)

    def test_parameters_preserve_existing_query_repetitions_blanks_and_escaped_values(self):
        params = ("feature=one", "feature=two", "empty=", "note=a&b=é / *")
        cases = (("--path", "entity/MNT-ADSI?existing=1"),
                 (self.base + "entity/MNT-ADSI?existing=1",))
        for args in cases:
            with self.subTest(args=args):
                flags = [flag for param in params for flag in ("--param", param)]
                code, out, err = self.run_cli("--server", self.base, "--raw", *flags, *args)
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["handle"], "MNT-ADSI")
                query = parse_qs(urlsplit(self.server.requests[-1][0]).query, keep_blank_values=True)
                self.assertEqual(query, {"existing": ["1"], "feature": ["one", "two"], "empty": [""], "note": ["a&b=é / *"]})
        self.client.lookup("MNT-ADSI", "entity", server=self.base, params=[("view", "full")])
        self.assertEqual(parse_qs(urlsplit(self.server.requests[-1][0]).query), {"view": ["full"]})

    def test_parameterized_queries_have_distinct_cache_entries(self):
        client = Client(timeout=3)
        for value in ("one", "two", "one"):
            client.lookup("MNT-ADSI", "entity", server=self.base, params=[("view", value)])
        self.assertEqual(len(self.server.requests), 2)

    def test_extended_queries_keep_credentials_on_the_selected_origin(self):
        client = Client(timeout=3, auth="user:pass")
        client.query_path("entities?fn=Example*", server=self.base)
        client.search("Example*", kind="ip", server=self.base)
        self.assertTrue(all(auth for _, auth in self.server.requests))
        self.assertEqual(client.memory, {})
        self.assertEqual(client.auth_origin, rdappy.origin(self.base))

    def test_invalid_search_combinations_and_parameters_do_not_send_requests(self):
        cases = (
            ("--search", "--type", "url", "example.test"),
            ("--search", "--entity", "Example*"),
            ("--search", "--entity", "--search-field", "ip", "example*"),
            ("--search-field", "handle", "MNT-ADSI"), ("--rdap-help",),
            ("--rdap-help", "--server", self.base, "MNT-ADSI"),
            ("--file", "record.json", "--param", "view=full"),
            ("--param", "missing-equals", "example.test"),
            ("--param", "=value", "example.test"),
            ("--param", "view=line\nbreak", "example.test"),
        )
        for args in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--no-config", *args])
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.server.requests, [])

    def test_invalid_search_values_fail_before_fetch(self):
        with patch.object(self.client, "fetch") as fetch:
            for kind, field, pattern in (("domain", "nsIp", "192.0.2.0/24"), ("nameserver", "ip", "999.0.0.1"),
                                         ("entity", "fn", ""), ("entity", "fn", "Name\nHeader")):
                with self.subTest(kind=kind, field=field, pattern=pattern), self.assertRaises(RdapError):
                    self.client.search(pattern, server=self.base, kind=kind, field=field)
            fetch.assert_not_called()

    def test_nested_entity_networks_and_asns_are_visible_without_recursive_fetches(self):
        record = dict(ENTITY, networks=[dict(NETWORK, name="Associated Network")],
                      autnums=[dict(AUTNUM, name="Associated AS")])
        output = Formatter().render(Response(record, self.base + "entity/MNT-ADSI"))
        for value in ("Example Maintainer", "CONTACT-RIPE", "Associated Network", "Associated AS", "AS64496"):
            self.assertIn(value, output)
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
