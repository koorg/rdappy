"""Offline tests for country hints and their registration-data provenance."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rdappy import Client, Formatter, Response, country_value, main, owner_summary


class CountryTests(unittest.TestCase):
    def contact(self, country="", cc=None, role="registrant"):
        return {"roles": [role], "vcardArray": ["vcard", [
            ["org", {}, "text", "Example Company"],
            ["adr", {"cc": cc} if cc is not None else {}, "text", ["", "", "", "", "", "", country]],
        ]]}

    def network(self, **fields):
        return dict({"objectClassName": "ip network", "startAddress": "192.0.2.0",
                     "endAddress": "192.0.2.255", "country": "US"}, **fields)

    def test_country_value_accepts_declared_values_and_rejects_placeholders(self):
        for value, expected in ((" fr ", "FR"), ("France", "France"), ("United  States", "United States"),
                                ("NA", "NA"), ("N/A", ""), ("ZZ", ""), ("EU", ""),
                                ("REDACTED FOR PRIVACY", ""), ("Not disclosed", ""), ("unknown", "")):
            with self.subTest(value=value):
                self.assertEqual(country_value(value), expected)
        for value in (None, False, 123, ["US"], {"country": "US"}, "US\x1b[2J", "US\nFR"):
            with self.subTest(value=value):
                self.assertEqual(country_value(value), "")
        self.assertEqual(country_value("France", code_only=True), "")
        self.assertEqual(country_value("us", code_only=True), "US")

    def test_registrant_address_precedes_network_registration(self):
        contact = self.contact("United States")
        contact["vcardArray"][1][1][1] = {"CC": "fr"}
        summary = owner_summary([Response(self.network(country="DE", entities=[contact]), "https://example.test/ip/192.0.2.0")])
        self.assertEqual(summary["countries"], ["FR"])
        self.assertEqual(summary["country_details"], [{"country": "FR", "basis": "registrant_address", "source": "https://example.test/ip/192.0.2.0"}])
        self.assertNotIn("DE", Formatter().render_owner(summary))

    def test_network_and_asn_registration_fallback_keep_contact_countries_separate(self):
        for data, basis in ((self.network(country="us"), "network_registration"),
                            ({"objectClassName": "autnum", "startAutnum": 64496, "country": "gb"}, "autnum_registration")):
            with self.subTest(basis=basis):
                summary = owner_summary([Response(data, "https://example.test/record")])
                expected = "US" if basis == "network_registration" else "GB"
                self.assertEqual(summary["countries"], [])
                self.assertEqual(summary["country_details"], [{"country": expected, "basis": basis, "source": "https://example.test/record"}])
                self.assertIn(expected, Formatter().render_owner(summary))

    def test_country_uses_only_direct_registrant_contacts(self):
        registrar = self.contact("US", role="registrar")
        registrar["entities"] = [self.contact("GB")]
        domain = {"objectClassName": "domain", "ldhName": "example.fr", "country": "FR",
                  "entities": [registrar, self.contact("CA", role="abuse")]}
        summary = owner_summary([Response(domain, "https://example.test/domain/example.fr")])
        self.assertEqual(summary["countries"], [])
        self.assertEqual(summary["country_details"], [])

    def test_invalid_cc_falls_back_to_explicit_country_component(self):
        for cc in (["US"], "ZZ", "invalid"):
            with self.subTest(cc=cc):
                data = {"objectClassName": "domain", "ldhName": "example.test", "entities": [self.contact("France", cc=cc)]}
                summary = owner_summary([Response(data, "https://example.test/record")])
                self.assertEqual(summary["countries"], ["France"])
                self.assertEqual(summary["country_details"][0]["basis"], "registrant_address")

    def test_country_evidence_deduplicates_and_preserves_conflicts(self):
        first = {"objectClassName": "domain", "ldhName": "example.test", "entities": [self.contact("FR"), self.contact("fr")]}
        second = dict(first, entities=[self.contact("FR"), self.contact("GB")])
        summary = owner_summary([Response(first, "https://example.test/registry"), Response(second, "https://example.test/registrar")])
        self.assertEqual(summary["countries"], ["FR", "GB"])
        self.assertEqual(len(summary["country_details"]), 3)
        self.assertEqual({entry["source"] for entry in summary["country_details"]}, {"https://example.test/registry", "https://example.test/registrar"})
        rendered = Formatter().render_owner(summary)
        self.assertEqual(rendered.count("FR"), 1)
        self.assertEqual(rendered.count("GB"), 1)

    def test_missing_country_ignores_redaction_markers_and_invalid_record_values(self):
        for value in ("ZZ", "XX", "unknown", ["FR"], False, None):
            with self.subTest(value=value):
                summary = owner_summary([Response(self.network(country=value, entities=[self.contact("REDACTED FOR PRIVACY")]), "https://example.test/record")])
                self.assertEqual(summary["countries"], [])
                self.assertEqual(summary["country_details"], [])
                self.assertNotIn("REDACTED", Formatter().render_owner(summary))

    def test_local_owner_json_has_country_provenance_without_requests(self):
        with tempfile.TemporaryDirectory(prefix=".rdappy-country-", dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(self.network()), encoding="utf-8")
            output = io.StringIO()
            with patch.object(Client, "fetch", side_effect=AssertionError("Unexpected request")), contextlib.redirect_stdout(output):
                self.assertEqual(main(["--no-config", "--owner", "--file", str(path), "--raw"]), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["countries"], [])
            self.assertEqual(summary["country_details"], [{"country": "US", "basis": "network_registration", "source": path.resolve().as_uri()}])


if __name__ == "__main__":
    unittest.main()
