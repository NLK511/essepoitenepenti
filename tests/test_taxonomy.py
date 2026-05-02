from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from scripts.deploy_watchlists import WATCHLIST_SPECS
from trade_proposer_app.services.default_jobs import DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS
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
    TRANSMISSION_CONFLICT_FLAGS_PATH,
    TRANSMISSION_BIASES_PATH,
    TRANSMISSION_CONTEXT_REGIMES_PATH,
    TRANSMISSION_WINDOWS_PATH,
    SHORTLIST_REASON_CODES_PATH,
    SHORTLIST_SELECTION_LANES_PATH,
    CALIBRATION_REVIEW_STATUSES_PATH,
    CALIBRATION_REASON_CODES_PATH,
    ACTION_REASON_CODES_PATH,
    CONTRADICTION_REASON_CODES_PATH,
    EVENT_SOURCE_PRIORITIES_PATH,
    EVENT_PERSISTENCE_STATES_PATH,
    EVENT_WINDOW_HINTS_PATH,
    EVENT_RECENCY_BUCKETS_PATH,
    TRANSMISSION_PRIMARY_DRIVERS_PATH,
    TRANSMISSION_TAGS_PATH,
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

    def test_default_watchlist_universe_is_fully_represented(self) -> None:
        service = TickerTaxonomyService()
        default_tickers = list(dict.fromkeys(ticker for spec in WATCHLIST_SPECS for ticker in spec["tickers"]))
        missing = [ticker for ticker in default_tickers if ticker not in service._taxonomy]

        self.assertEqual([], missing)
        self.assertEqual(750, len(default_tickers))

    def test_default_watchlists_include_post_close_recommendation_evaluation_jobs(self) -> None:
        self.assertEqual([spec["name"] for spec in DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS], [
            "Auto: Recommendation Evaluation APAC Close",
            "Auto: Recommendation Evaluation Europe Close",
            "Auto: Recommendation Evaluation US Close",
        ])
        self.assertEqual([spec["cron"] for spec in DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS], ["35 08 * * MON-FRI", "05 17 * * MON-FRI", "35 20 * * MON-FRI"])

    def test_split_taxonomy_files_exist_and_are_loaded(self) -> None:
        self.assertTrue(TICKERS_PATH.exists())
        self.assertTrue(INDUSTRIES_PATH.exists())
        self.assertTrue(SECTORS_PATH.exists())
        self.assertTrue(RELATIONSHIPS_PATH.exists())
        self.assertTrue(EVENT_VOCAB_PATH.exists())
        self.assertTrue(THEMES_PATH.exists())
        self.assertTrue(MACRO_CHANNELS_PATH.exists())
        self.assertTrue(TRANSMISSION_CHANNELS_PATH.exists())
        self.assertTrue(TRANSMISSION_TAGS_PATH.exists())
        self.assertTrue(TRANSMISSION_PRIMARY_DRIVERS_PATH.exists())
        self.assertTrue(TRANSMISSION_CONFLICT_FLAGS_PATH.exists())
        self.assertTrue(TRANSMISSION_BIASES_PATH.exists())
        self.assertTrue(TRANSMISSION_CONTEXT_REGIMES_PATH.exists())
        self.assertTrue(TRANSMISSION_WINDOWS_PATH.exists())
        self.assertTrue(SHORTLIST_REASON_CODES_PATH.exists())
        self.assertTrue(SHORTLIST_SELECTION_LANES_PATH.exists())
        self.assertTrue(CALIBRATION_REVIEW_STATUSES_PATH.exists())
        self.assertTrue(CALIBRATION_REASON_CODES_PATH.exists())
        self.assertTrue(ACTION_REASON_CODES_PATH.exists())
        self.assertTrue(CONTRADICTION_REASON_CODES_PATH.exists())
        self.assertTrue(EVENT_SOURCE_PRIORITIES_PATH.exists())
        self.assertTrue(EVENT_PERSISTENCE_STATES_PATH.exists())
        self.assertTrue(EVENT_WINDOW_HINTS_PATH.exists())
        self.assertTrue(EVENT_RECENCY_BUCKETS_PATH.exists())
        self.assertTrue(RELATIONSHIP_TYPES_PATH.exists())
        self.assertTrue(RELATIONSHIP_TARGET_KINDS_PATH.exists())

        service = TickerTaxonomyService()
        overview = service.taxonomy_overview()
        self.assertEqual(overview["source_mode"], "split")
        self.assertGreaterEqual(overview["sector_count"], 8)
        self.assertGreaterEqual(overview["event_vocab_group_count"], 12)
        self.assertGreaterEqual(overview["theme_count"], 40)
        self.assertGreaterEqual(overview["theme_parent_count"], 10)
        self.assertGreaterEqual(overview["macro_channel_count"], 20)
        self.assertGreaterEqual(overview["macro_channel_parent_count"], 10)
        self.assertGreaterEqual(overview["transmission_channel_count"], 30)
        self.assertGreaterEqual(overview["transmission_tag_count"], 3)
        self.assertGreaterEqual(overview["transmission_primary_driver_count"], 8)
        self.assertGreaterEqual(overview["transmission_conflict_flag_count"], 5)
        self.assertGreaterEqual(overview["transmission_bias_count"], 4)
        self.assertGreaterEqual(overview["transmission_context_regime_count"], 6)
        self.assertGreaterEqual(overview["transmission_window_count"], 5)
        self.assertGreaterEqual(overview["shortlist_reason_code_count"], 6)
        self.assertGreaterEqual(overview["shortlist_selection_lane_count"], 2)
        self.assertGreaterEqual(overview["calibration_review_status_count"], 5)
        self.assertGreaterEqual(overview["calibration_reason_code_count"], 20)
        self.assertGreaterEqual(overview["action_reason_code_count"], 8)
        self.assertGreaterEqual(overview["contradiction_reason_code_count"], 3)
        self.assertGreaterEqual(overview["event_source_priority_count"], 4)
        self.assertGreaterEqual(overview["event_persistence_state_count"], 4)
        self.assertGreaterEqual(overview["event_window_hint_count"], 4)
        self.assertGreaterEqual(overview["event_recency_bucket_count"], 4)
        self.assertGreaterEqual(overview["relationship_type_count"], 8)
        self.assertGreaterEqual(overview["relationship_target_kind_count"], 4)
        self.assertGreaterEqual(overview["relationship_direction_count"], 20)
        self.assertGreaterEqual(overview["relationship_mechanism_count"], 20)
        self.assertGreaterEqual(overview["relationship_confidence_count"], 20)
        self.assertGreaterEqual(overview["relationship_provenance_count"], 20)
        self.assertGreaterEqual(overview["derived_relationship_count"], 20)
        self.assertGreaterEqual(overview["ticker_industry_link_count"], 100)
        self.assertGreaterEqual(overview["ticker_sector_link_count"], 700)
        self.assertGreaterEqual(overview["ticker_macro_link_count"], 100)
        self.assertGreaterEqual(overview["ticker_supplier_link_count"], 10)
        self.assertGreaterEqual(overview["ticker_customer_link_count"], 10)
        self.assertGreaterEqual(overview["ticker_with_supplier_count"], 8)
        self.assertGreaterEqual(overview["ticker_with_customer_count"], 8)

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
        self.assertEqual(service.get_transmission_tag_definition("macro_dominant")["key"], "macro_dominant")
        self.assertEqual(service.get_transmission_primary_driver_definition("industry_context_support")["key"], "industry_context_support")
        self.assertEqual(service.get_transmission_conflict_flag_definition("timing_conflict")["key"], "timing_conflict")
        self.assertEqual(service.get_transmission_bias_definition("supportive")["key"], "tailwind")
        self.assertEqual(service.derive_transmission_bias({"context_bias": "supportive"}), "tailwind")
        self.assertEqual(service.get_transmission_context_regime_definition("context_plus_catalyst")["key"], "context_plus_catalyst")
        self.assertEqual(service.get_transmission_window_definition("2d_5d")["label"], "2d-5d")
        self.assertEqual(service.get_shortlist_reason_definition("below_confidence_threshold")["label"], "below confidence threshold")
        self.assertEqual(service.get_shortlist_selection_lane_definition("catalyst")["key"], "catalyst")
        self.assertEqual(service.get_calibration_review_status_definition("usable_for_gating")["label"], "usable for gating")
        self.assertEqual(service.get_calibration_reason_definition("context_regime_underperforming")["label"], "context regime underperforming")
        self.assertEqual(service.get_action_reason_definition("context_transmission_headwind")["label"], "context transmission headwind")
        self.assertEqual(service.get_contradiction_reason_definition("mixed_directional_evidence")["label"], "mixed directional evidence")
        self.assertEqual(service.get_event_source_priority_definition("official")["label"], "official")
        self.assertEqual(service.get_event_persistence_state_definition("escalating")["label"], "escalating")
        self.assertEqual(service.get_event_window_hint_definition("2d_5d")["label"], "2d-5d")
        self.assertEqual(service.get_event_recency_bucket_definition("fresh")["label"], "fresh")
        self.assertEqual(service.derive_transmission_context_regime({"context_bias": "tailwind", "transmission_tags": ["macro_dominant", "catalyst_active"]}), "context_plus_catalyst")
        self.assertEqual(service.get_analysis_bucket_label("transmission_bias", "tailwind"), "tailwind")
        self.assertEqual(service.get_theme_definition("consumer_electronics")["parent"], "consumer")
        self.assertEqual(service.get_theme_definition("ai_capex")["parent"], "ai")
        self.assertEqual(service.get_macro_channel_definition("yield_curve")["parent"], "rates")
        self.assertEqual(service.get_macro_channel_definition("cloud_capex")["parent"], "enterprise_spend")
        self.assertIn("consumer_spending", aapl_profile["exposure_channels"])
        self.assertIn("consumer", service.get_industry_profile("AAPL")["queries"])
        self.assertIn("enterprise spend", service.build_query_profile("NVDA")["macro_queries"])

    def test_provider_backed_reclassification_and_domicile_fill(self) -> None:
        service = TickerTaxonomyService()

        abbv_profile = service.get_ticker_profile("ABBV")
        self.assertEqual(abbv_profile["domicile"], "United States")

        adsk_profile = service.get_ticker_profile("ADSK")
        self.assertEqual(adsk_profile["industry"], "Software - Application")

        nee_industry_profile = service.get_industry_profile("NEE")
        self.assertEqual(nee_industry_profile["subject_label"], "Utilities - Regulated Electric")
        self.assertEqual(nee_industry_profile["resolution_mode"], "taxonomy")
        self.assertIn("Utilities - Regulated Electric", nee_industry_profile["queries"])

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
        self.assertEqual(industry_profile["subject_key"], "software_infrastructure")
        self.assertEqual(industry_profile["subject_label"], "Software - Infrastructure")
        self.assertEqual(industry_profile["resolution_mode"], "taxonomy")
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

        software_relationships = service.list_relationships("software", direction="outbound")
        self.assertTrue(any(item["target"] == "cloud_capex" and item.get("direction") == "positive" for item in software_relationships))
        self.assertTrue(any(item["target"] == "cloud_capex" and item.get("mechanism") == "renewal_and_expansion" for item in software_relationships))
        self.assertTrue(any(item["target"] == "cloud_capex" and item.get("confidence") == "high" for item in software_relationships))
        self.assertTrue(any(item["target"] == "cloud_capex" and item.get("relationship_score", 0.0) > 0.8 for item in software_relationships))

        ticker_relationships = service.get_ticker_relationships("AAPL")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "SONY" for item in ticker_relationships))
        self.assertTrue(any(item["type"] == "supplier_to" and item["target"] == "TSM" for item in ticker_relationships))

    def test_top_watchlist_ticker_relationship_depth_is_present(self) -> None:
        service = TickerTaxonomyService()
        first_100 = list(dict.fromkeys(ticker for spec in WATCHLIST_SPECS[:2] for ticker in spec["tickers"]))
        tickers_with_supply_chain_depth = [
            ticker
            for ticker in first_100
            if service.get_ticker_profile(ticker).get("suppliers") or service.get_ticker_profile(ticker).get("customers")
        ]
        self.assertGreaterEqual(len(tickers_with_supply_chain_depth), 10)

        tsm_relationships = service.get_ticker_relationships("2330.TW")
        self.assertTrue(any(item["type"] == "supplier_to" and item["target"] == "ASML.AS" for item in tsm_relationships))
        self.assertTrue(any(item["type"] == "customer_of" and item["target"] == "AAPL" for item in tsm_relationships))

        samsung_relationships = service.get_ticker_relationships("005930.KS")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "000660.KS" for item in samsung_relationships))
        self.assertTrue(any(item["type"] == "customer_of" and item["target"] == "AAPL" for item in samsung_relationships))

    def test_us_and_europe_mega_cap_relationship_depth_is_present(self) -> None:
        service = TickerTaxonomyService()

        aapl_profile = service.get_ticker_profile("AAPL")
        self.assertIn("TSM", aapl_profile["suppliers"])
        self.assertIn("005930.KS", aapl_profile["suppliers"])
        aapl_relationships = service.get_ticker_relationships("AAPL")
        self.assertTrue(any(item["type"] == "supplier_to" and item["target"] == "TSM" for item in aapl_relationships))
        self.assertTrue(any(item["type"] == "supplier_to" and item["target"] == "005930.KS" for item in aapl_relationships))
        self.assertTrue(any(item["type"] == "belongs_to_sector" and item["target"] == "information_technology" for item in aapl_relationships))
        self.assertTrue(any(item["type"] == "linked_macro_channel" and item["target"] == "consumer_spending" for item in aapl_relationships))

        sap_relationships = service.get_ticker_relationships("SAP.DE")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "ORCL" for item in sap_relationships))
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "MSFT" for item in sap_relationships))

        asml_relationships = service.get_ticker_relationships("ASML.AS")
        self.assertTrue(any(item["type"] == "customer_of" and item["target"] == "TSM" for item in asml_relationships))
        self.assertTrue(any(item["type"] == "customer_of" and item["target"] == "005930.KS" for item in asml_relationships))

        novo_relationships = service.get_ticker_relationships("NOVO-B.CO")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "AZN.L" for item in novo_relationships))

    def test_mid_cap_industrial_and_financial_relationship_depth_is_present(self) -> None:
        service = TickerTaxonomyService()

        jpm_relationships = service.get_ticker_relationships("JPM")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "BAC" for item in jpm_relationships))
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "GS" for item in jpm_relationships))
        self.assertTrue(any(item["type"] == "belongs_to_sector" and item["target"] == "financials" for item in jpm_relationships))
        self.assertTrue(any(item["type"] == "linked_macro_channel" and item["target"] == "yield_curve" for item in jpm_relationships))

        cat_relationships = service.get_ticker_relationships("CAT")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "DE" for item in cat_relationships))
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "RTX" for item in cat_relationships))
        self.assertTrue(any(item["type"] == "belongs_to_sector" and item["target"] == "industrials" for item in cat_relationships))
        self.assertTrue(any(item["type"] == "linked_macro_channel" and item["target"] == "infrastructure_spend" for item in cat_relationships))

        amt_profile = service.get_ticker_profile("AMT")
        self.assertIn("TMUS", amt_profile["customers"])
        self.assertIn("VZ", amt_profile["customers"])
        amt_relationships = service.get_ticker_relationships("AMT")
        self.assertTrue(any(item["type"] == "customer_of" and item["target"] == "TMUS" for item in amt_relationships))
        self.assertTrue(any(item["type"] == "customer_of" and item["target"] == "VZ" for item in amt_relationships))

        plld_relationships = service.get_ticker_relationships("PLD")
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "AMT" for item in plld_relationships))
        self.assertTrue(any(item["type"] == "peer_of" and item["target"] == "EQIX" for item in plld_relationships))

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
