import unittest

from backend.models import OfficialMetadata, ParseReference
from backend.parser import parse_reference_section
from backend.verification import _metadata_conflicts, _pick_official, evaluate_support


class AccuracyRegressionTests(unittest.TestCase):
    def test_directional_contradiction_is_high_risk(self) -> None:
        claim = "urban green spaces increase native plant biodiversity"
        reference_text = (
            "Urban green space conversion can reduce native plant biodiversity "
            "when management favors ornamental species."
        )

        result = evaluate_support(claim, reference_text, context=claim)

        self.assertEqual(result.status, "red")

    def test_chinese_claim_with_shared_terms_can_be_supported(self) -> None:
        claim = "\u6e7f\u5730\u6062\u590d\u63d0\u9ad8\u571f\u58e4\u78b3\u50a8\u91cf"
        reference_text = (
            "\u6e7f\u5730\u6062\u590d\u53ef\u4ee5\u589e\u52a0"
            "\u571f\u58e4\u78b3\u50a8\u91cf\u5e76\u6539\u5584"
            "\u751f\u6001\u7cfb\u7edf\u529f\u80fd\u3002"
        )

        result = evaluate_support(claim, reference_text, context=claim)

        self.assertEqual(result.status, "green")

    def test_titleless_doiless_reference_is_not_green_from_weak_identity(self) -> None:
        reference = ParseReference(
            ref_id="1",
            raw="Smith J. Nature 2020;10:100-110.",
            index=1,
            authors=["Smith J"],
            first_author="Smith",
            year=2020,
            journal="Nature",
        )
        official = OfficialMetadata(
            source="crossref",
            title="Dynamics of Lyman-alpha blobs",
            authors=["Smith, J."],
            journal="Nature",
            year=2020,
            doi="10.1038/example",
        )

        conflicts, status, score = _metadata_conflicts(reference, official, [2020])

        self.assertEqual(conflicts, [])
        self.assertEqual(status, "white")
        self.assertLessEqual(score, 0.5)

    def test_doiless_reference_can_be_verified_by_metadata_fields(self) -> None:
        reference = ParseReference(
            ref_id="2",
            raw=(
                "Nahlik, A. M., & Fennessy, M. S. (2016). "
                "Carbon storage in US wetlands. Nature Communications, 7, 13835."
            ),
            index=2,
            authors=["Nahlik, A. M.", "Fennessy, M. S."],
            first_author="Nahlik",
            year=2016,
            title="Carbon storage in US wetlands",
        )
        official = OfficialMetadata(
            source="crossref",
            title="Carbon storage in US wetlands",
            authors=["Nahlik, A. M.", "Fennessy, M. S."],
            journal="Nature Communications",
            year=2016,
            doi="10.1038/ncomms13835",
        )

        conflicts, status, score = _metadata_conflicts(reference, official, [2016])

        self.assertEqual(conflicts, [])
        self.assertEqual(status, "green")
        self.assertGreaterEqual(score, 0.85)

    def test_pick_official_prefers_best_metadata_match_without_doi(self) -> None:
        reference = ParseReference(
            ref_id="3",
            raw="Smith, J. (2020). Target article title. Journal of Useful Results.",
            index=3,
            authors=["Smith, J."],
            first_author="Smith",
            year=2020,
            title="Target article title",
            journal="Journal of Useful Results",
        )
        source_metadata = {
            "crossref": OfficialMetadata(
                source="crossref",
                title="Different article about another topic",
                authors=["Smith, J."],
                journal="Journal of Useful Results",
                year=2020,
            ),
            "semanticscholar": OfficialMetadata(
                source="semanticscholar",
                title="Target article title",
                authors=["Smith, John"],
                journal="Journal of Useful Results",
                year=2020,
            ),
        }

        official = _pick_official(source_metadata, reference=reference)

        self.assertIsNotNone(official)
        self.assertEqual(official.source, "semanticscholar")

    def test_parser_extracts_journal_for_doiless_reference_with_title(self) -> None:
        [reference] = parse_reference_section(
            "[1] Nahlik, A. M., & Fennessy, M. S. (2016). "
            "Carbon storage in US wetlands. Nature Communications, 7, 13835."
        )

        self.assertEqual(reference.title, "Carbon storage in US wetlands")
        self.assertEqual(reference.journal, "Nature Communications")


if __name__ == "__main__":
    unittest.main()
