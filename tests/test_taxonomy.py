from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from trade_proposer_app.services.taxonomy import (
    EVENT_VOCAB_PATH,
    INDUSTRIES_PATH,
    RELATIONSHIPS_PATH,
    SECTORS_PATH,
    TICKERS_PATH,
    THEMES_PATH,
    MACRO_CHANNELS_PATH,
    RELATIONSHIP_TARGET_KINDS_PATH,
    RELATIONSHIP_TYPES_PATH,
    TRANSMISSION_CHANNELS_PATH,
    TickerTaxonomyService,
)


class TickerTaxonomyServiceTests(unittest.TestCase):
    def test_taxonomy_has_broad_multi_region_coverage(self) -> None:
        service = TickerTaxonomyService()
        profiles = [service.get_ticker_profile(ticker) for ticker in service._taxonomy]

        self.assertGreaterEqual(len(profiles), 40)
        industries = {profile["industry"] for profile in profiles if profile.get("industry")}
        regions = {profile["region"] for profile in profiles if profile.get("region")}

        self.assertGreaterEqual(len(industries), 12)
        self.assertTrue({"US", "Europe", "Asia-Pacific"}.issubset(regions))

    def test_split_taxonomy_files_exist_and_are_loaded(self) -> None:
        self.assertTrue(TICKERS_PATH.exists())
        self.assertTrue(INDUSTRIES_PATH.exists())
        self.assertTrue(SECTORS_PATH.exists())
        self.assertTrue(RELATIONSHIPS_PATH.exists())
        self.assertTrue(EVENT_VOCAB_PATH.exists())
        self.assertTrue(THEMES_PATH.exists())
        self.assertTrue(MACRO_CHANNELS_PATH.exists())
        self.assertTrue(TRANSMISSION_CHANNELS_PATH.exists())
        self.assertTrue(RELATIONSHIP_TYPES_PATH.exists())
        self.assertTrue(RELATIONSHIP_TARGET_KINDS_PATH.exists())

        service = TickerTaxonomyService()
        overview = service.taxonomy_overview()
        self.assertEqual(overview["source_mode"], "split")
        self.assertGreaterEqual(overview["sector_count"], 8)
        self.assertGreaterEqual(overview["event_vocab_group_count"], 12)
        self.assertGreaterEqual(overview["theme_count"], 40)
        self.assertGreaterEqual(overview["macro_channel_count"], 20)
        self.assertGreaterEqual(overview["transmission_channel_count"], 30)
        self.assertGreaterEqual(overview["relationship_type_count"], 8)
        self.assertGreaterEqual(overview["relationship_target_kind_count"], 4)
        self.assertGreaterEqual(overview["derived_relationship_count"], 20)

    def test_query_profile_and_industry_profile_use_explicit_industry_definitions(self) -> None:
        service = TickerTaxonomyService()

        nvda_query_profile = service.build_query_profile("NVDA")
        self.assertIn("gpu demand", nvda_query_profile["industry_queries"])
        self.assertIn("semiconductor demand", nvda_query_profile["industry_queries"])
        self.assertIn("ai capex", nvda_query_profile["macro_queries"])
        self.assertIn("Blackwell", nvda_query_profile["ticker_queries"])

        asml_profile = service.get_ticker_profile("ASML")
        self.assertEqual(asml_profile["region"], "Europe")
        self.assertEqual(asml_profile["subindustry"], "Lithography equipment")
        self.assertIn("fab_capex", asml_profile["exposure_channels"])
        self.assertIn("capex", asml_profile["event_vocab"])

        asml_industry_profile = service.get_industry_profile("ASML")
        self.assertEqual(asml_industry_profile["subject_key"], "semiconductor_equipment")
        self.assertIn("Lithography equipment", asml_industry_profile["queries"])
        self.assertIn("fab_capex", asml_industry_profile["transmission_channels"])
        self.assertIn("Information Technology", asml_industry_profile["sector_definition"]["label"])

        aapl_profile = service.get_ticker_profile("AAPL")
        self.assertIn("consumer spending", aapl_profile["macro_sensitivity"])
        self.assertIn("consumer spending", service.build_query_profile("AAPL")["macro_queries"])
        self.assertEqual(service.get_theme_definition("consumer spend")["key"], "consumer_spending")
        self.assertEqual(service.get_transmission_channel_definition("supply_chain")["key"], "supply_chain")
        self.assertEqual(service.get_relationship_type_definition("macro_link")["key"], "linked_macro_channel")
        self.assertEqual(service.get_relationship_target_kind_definition("macro")["key"], "macro_channel")
        self.assertIn("consumer_spending", aapl_profile["exposure_channels"])

    def test_list_industry_profiles_groups_multiple_tickers_and_relationships(self) -> None:
        service = TickerTaxonomyService()
        profiles = {profile["subject_key"]: profile for profile in service.list_industry_profiles()}

        self.assertIn("consumer_electronics", profiles)
        self.assertIn("semiconductors", profiles)
        self.assertIn("software", profiles)
        self.assertIn("information_technology", profiles)
        self.assertGreaterEqual(len(profiles["consumer_electronics"]["tickers"]), 2)
        self.assertGreaterEqual(len(profiles["semiconductors"]["tickers"]), 4)
        self.assertIn("NVDA", profiles["semiconductors"]["tickers"])
        self.assertIn("TSM", profiles["semiconductors"]["tickers"])
        self.assertIn("ai capex", profiles["semiconductors"]["macro_sensitivity"])
        self.assertTrue(any(item["type"] == "hurt_by" for item in profiles["airlines"]["relationships"]))

    def test_unknown_ticker_can_fall_back_to_external_sector_metadata(self) -> None:
        service = TickerTaxonomyService(
            metadata_provider=lambda ticker: {
                "company_name": "Acme Cloud",
                "sector": "Technology",
                "industry": "Software - Infrastructure",
                "region": "US",
                "domicile": "US",
            } if ticker == "ZZZZ" else {},
        )

        ticker_profile = service.get_ticker_profile("ZZZZ")
        industry_profile = service.get_industry_profile("ZZZZ")

        self.assertEqual(ticker_profile["company_name"], "Acme Cloud")
        self.assertEqual(ticker_profile["sector"], "Technology")
        self.assertEqual(ticker_profile["industry"], "Software - Infrastructure")
        self.assertEqual(industry_profile["subject_key"], "information_technology")
        self.assertEqual(industry_profile["subject_label"], "Information Technology")
        self.assertEqual(industry_profile["resolution_mode"], "sector_fallback")
        self.assertIn("Software - Infrastructure", industry_profile["queries"])
        self.assertIn("Technology", industry_profile["queries"])

    def test_explicit_industry_definitions_and_relationships_are_available(self) -> None:
        service = TickerTaxonomyService()

        airlines = service.get_industry_definition("airlines")
        self.assertEqual(airlines["label"], "Airlines")
        self.assertIn("travel_demand", airlines["transmission_channels"])

        relationships = service.list_relationships("airlines", direction="outbound")
        self.assertTrue(any(item["target"] == "oil_and_gas" and item["type"] == "hurt_by" for item in relationships))
        self.assertTrue(any(item["target"] == "consumer_spending" and item["target_kind"] == "macro_channel" for item in relationships))
        self.assertTrue(any(item["target"] == "consumer_spending" and item.get("target_label") == "consumer spending" for item in relationships))
        self.assertTrue(any(item.get("channel") == "travel_demand" and item.get("channel_label") == "travel demand" for item in relationships))
        self.assertTrue(any(item["type"] == "belongs_to_sector" and item["target_kind"] == "sector" and item["target"] == "industrials" for item in relationships))

        consumer_electronics_relationships = service.list_relationships("consumer_electronics", direction="outbound")
        self.assertTrue(any(item["type"] == "linked_macro_channel" and item["target"] == "consumer_spending" for item in consumer_electronics_relationships))
        self.assertTrue(any(item["type"] == "exposed_to_theme" and item["target_kind"] == "theme" for item in consumer_electronics_relationships))
        self.assertTrue(any(item.get("type_label") == "linked macro channel" for item in consumer_electronics_relationships))

        ticker_relationships = service.get_ticker_relationships("AAPL")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "SONY" for item in ticker_relationships))
        self.assertTrue(any(item["type"] == "supplier_to" and item["target"] == "TSM" for item in ticker_relationships))

    def test_validation_and_report_scripts_pass(self) -> None:
        root = Path(__file__).resolve().parents[1]
        validate = subprocess.run(
            [sys.executable, str(root / "scripts" / "validate_taxonomy.py")],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(validate.returncode, 0, msg=validate.stdout + validate.stderr)
        self.assertIn("Validation passed.", validate.stdout)
        self.assertIn("Taxonomy source mode: split", validate.stdout)

        report = subprocess.run(
            [sys.executable, str(root / "scripts" / "taxonomy_report.py")],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(report.returncode, 0, msg=report.stdout + report.stderr)
        self.assertIn("Taxonomy overview", report.stdout)
        self.assertIn("Industry coverage", report.stdout)
        self.assertIn("Semiconductors", report.stdout)


if __name__ == "__main__":
    unittest.main()
