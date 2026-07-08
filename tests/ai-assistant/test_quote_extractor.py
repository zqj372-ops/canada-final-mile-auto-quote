from decimal import Decimal

from packages.ai_assistant.model_client import AIResponse
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, apply_deterministic_extraction, extract_quote_draft


class FakeAIClient:
    def __init__(self, content: str):
        self.content = content

    def complete(self, _messages: object) -> AIResponse:
        return AIResponse(content=self.content)


def test_deterministic_extraction_normalizes_mixed_units() -> None:
    raw = """
    2pcs 67in x 55in x 34in 900lbs
    1700mm*1400mm*740mm 360.5kg
    205 Main Street
    New Norway Alberta Canada
    T0B3L0
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=10), raw)

    assert draft.piece_count == 3
    assert draft.postal_code == "T0B 3L0"
    assert draft.province == "AB"
    assert draft.weight_kg == Decimal("1177.0")
    assert draft.cbm == Decimal("5.867")
    assert draft.longest_side_cm == Decimal("170.2")


def test_deterministic_extraction_matches_sample_totals() -> None:
    raw = """
    170*140*87  409.8kg
    170*140*74  360.5KG
    170*87*82   221.5KG
    71*61*71    92.5KG
    71*61*71    68.5KG
    71*61*71    95KG
    71*61*71    169KG
    205 Main Street
    New Norway Alberta Canada
    T0B 3L0
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 7
    assert draft.cbm == Decimal("6.275")
    assert draft.weight_kg == Decimal("1416.8")
    assert draft.postal_code == "T0B 3L0"
    assert draft.province == "AB"


def test_deterministic_extraction_infers_large_unlabeled_dimensions_as_mm() -> None:
    raw = """
    440 Hodgson Blvd NW, Edmonton, AB T6R 3E9加拿大
    产品售水机，2.5CBM，224kg左右 1080*910*2160
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 1
    assert draft.cbm == Decimal("2.500")
    assert draft.weight_kg == Decimal("224.0")
    assert draft.longest_side_cm == Decimal("216.0")
    assert draft.postal_code == "T6R 3E9"
    assert draft.city == "Edmonton"
    assert draft.province == "AB"


def test_deterministic_extraction_reads_aggregate_cbm_weight_cartons() -> None:
    raw = """
    加拿大地址：1055 Flagship Way, unit A, Pickering ON, L1X 0P2
    品名：棉枕
    常规纸箱尺寸  99箱   11.7cbm   1367kg
    麻烦告知一下派送费，谢谢@运营中心-周秋吉(Autumn)

    ---
    前台已确认字段，仅用于字段提取，不允许 AI 计算价格：
    packaging_type=carton
    address_type=commercial
    requires_liftgate=false
    requires_pallet_jack=false
    requires_appointment=false
    detention_minutes=0
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "1055 Flagship Way, unit A"
    assert draft.city == "Pickering"
    assert draft.piece_count == 99
    assert draft.cbm == Decimal("11.700")
    assert draft.weight_kg == Decimal("1367.0")
    assert draft.postal_code == "L1X 0P2"
    assert draft.province == "ON"
    assert draft.packaging_type == "carton"
    assert draft.address_type == "commercial"
    assert draft.requires_liftgate is False
    assert draft.requires_pallet_jack is False
    assert draft.requires_appointment is False


def test_deterministic_extraction_reads_carton_specs_with_trailing_quantities() -> None:
    raw = """
    56件货.  Suite 8, 7000 McLeod Rd, Niagara Falls, ON L2G 7K3
    Canada
    箱规：58*62*46cm  重约：18.7KG/箱 22件
    箱规：55*58*46cm  重约：17.2KG/箱 22件
    筷子箱规：43*29*42cm  重约：16.8KG/箱 10件
    牙签箱规：49*43*32.5cm  重约：11.6KG/箱 2件
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "Suite 8, 7000 McLeod Rd"
    assert draft.city == "Niagara Falls"
    assert draft.postal_code == "L2G 7K3"
    assert draft.province == "ON"
    assert draft.piece_count == 56
    assert draft.cbm == Decimal("7.528")
    assert draft.weight_kg == Decimal("981.0")
    assert draft.longest_side_cm == Decimal("62.0")


def test_deterministic_extraction_prefers_declared_totals_for_single_carton_spec() -> None:
    raw = """
    厨房不锈钢水龙头
    HScode： 8481809000
    62.5*59.5*37.5CM/箱 23.5kg
    一共15箱 合计：352.5kg 2.18CBM
    收件地址：9-9699 Sills Ave, 9-9699 Sills Ave, V6Y0C8
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "9-9699 Sills Ave"
    assert draft.postal_code == "V6Y 0C8"
    assert draft.piece_count == 15
    assert draft.cbm == Decimal("2.180")
    assert draft.weight_kg == Decimal("352.5")
    assert draft.longest_side_cm == Decimal("62.5")


def test_deterministic_extraction_reads_richmond_faucet_sample() -> None:
    raw = """
    厨房不锈钢水龙头
    HScode： 8481809000
    62.5*59.5*37.5CM/箱   23.5kg
    一共15箱  合计：352.5kg  2.18CBM
    9699 Sills Ave #8, Richmond, BC V6Y 0C8加拿大
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "9699 Sills Ave #8"
    assert draft.city == "Richmond"
    assert draft.province == "BC"
    assert draft.postal_code == "V6Y 0C8"
    assert draft.piece_count == 15
    assert draft.cbm == Decimal("2.180")
    assert draft.weight_kg == Decimal("352.5")
    assert draft.longest_side_cm == Decimal("62.5")


def test_deterministic_extraction_does_not_read_cbm_decimal_as_piece_count() -> None:
    raw = """
    20箱重型网架。材质：铁+塑料网
    单箱规：144*74*18CM，单箱毛重55KG 纸箱包装
    共计3.84方 1100KG
    Delivery address: 480 1st Ave N, Saskatoon, SK S7K 1X6, Canada
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "480 1st Ave N"
    assert draft.city == "Saskatoon"
    assert draft.province == "SK"
    assert draft.postal_code == "S7K 1X6"
    assert draft.piece_count == 20
    assert draft.cbm == Decimal("3.840")
    assert draft.weight_kg == Decimal("1100.0")
    assert draft.longest_side_cm == Decimal("144.0")


def test_deterministic_extraction_keeps_dimension_quantities_without_item_weight() -> None:
    raw = """
    加拿大地址：3771 Jacombs Rd #340. Richmond,
    BC V6V 2L9
    品名：玻璃纤维增强水泥
    尺寸：113*79*12cm  14箱   63*63*11cm  28箱
    总重：2.73cbm  579kg
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 42
    assert draft.cbm == Decimal("2.730")
    assert draft.weight_kg == Decimal("579.0")
    assert draft.longest_side_cm == Decimal("113.0")
    assert draft.postal_code == "V6V 2L9"
    assert draft.province == "BC"


def test_deterministic_extraction_overrides_ai_weight_as_piece_count() -> None:
    raw = """
    体积重量：2700*1100*1700mm 5.1CBM  重量： 共1630KG
    数量： 共1件
    产品类型： 柴油发电机 100KW
    地址： 436 route 275
    Sainte-Marguerite de dorchester
    province Québec
    pays Canada
    G0S2X0
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(piece_count=1630, confidence=85), raw)

    assert draft.address_line == "436 route 275"
    assert draft.city == "Sainte-Marguerite de dorchester"
    assert draft.province == "QC"
    assert draft.postal_code == "G0S 2X0"
    assert draft.piece_count == 1
    assert draft.cbm == Decimal("5.100")
    assert draft.weight_kg == Decimal("1630.0")
    assert draft.longest_side_cm == Decimal("270.0")


def test_deterministic_extraction_clears_suspicious_model_piece_count() -> None:
    raw = """
    1300 Stewart St
    Vancouver BC V5L 4X5
    1.62CBM 1340kg
    最长边约300cm
    """

    draft = apply_deterministic_extraction(
        AIExtractedQuoteDraft(
            piece_count=2250,
            cbm=Decimal("1.62"),
            weight_kg=Decimal("1340"),
            longest_side_cm=Decimal("300"),
            confidence=85,
        ),
        raw,
    )

    assert draft.piece_count is None
    assert "suspicious model piece_count=2250" in (draft.extraction_notes or "")


def test_deterministic_extraction_reads_dimension_weight_table_with_labeled_address() -> None:
    raw = """
    国家：CA
    收货人：Craig Shipley
    电话：9052993081
    州省：ON
    城市：Paris
    邮编：N3L3N6
    地址1：20 Woodslee ave
    长                 宽                高                  围长             重量
    290 134.5 76 711 292.5
    281 135 148.5 848 1500
    216 164 173.5 891 900
    88 53 94 376 69
    169 130.5 163 756 770
    210 74 156 670 242
    85.5 86.5 224.5 568.5 170
    119.5 74.5 149 537 232.5
    107.5 84.5 116.5 500.5 220
    139.5 119 179 696 248
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "20 Woodslee ave"
    assert draft.city == "Paris"
    assert draft.province == "ON"
    assert draft.postal_code == "N3L 3N6"
    assert draft.piece_count == 10
    assert draft.cbm == Decimal("28.218")
    assert draft.weight_kg == Decimal("4644.0")
    assert draft.longest_side_cm == Decimal("290.0")


def test_deterministic_extraction_clears_placeholder_city_from_model() -> None:
    raw = """
    厨房不锈钢水龙头
    62.5*59.5*37.5CM/箱 23.5kg
    一共15箱 合计：352.5kg 2.18CBM
    收件地址：9-9699 Sills Ave, 9-9699 Sills Ave, V6Y0C8
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(city="---", confidence=80), raw)

    assert draft.city is None
    assert draft.postal_code == "V6Y 0C8"
    assert draft.piece_count == 15


def test_extract_quote_draft_accepts_json_wrapped_by_think_text() -> None:
    content = """
    <think>Need to parse fields.</think>
    Here is the JSON:
    {
      "address_line": "205 Main Street",
      "postal_code": "T0B 3L0",
      "city": "New Norway",
      "province": "AB",
      "cbm": 6.275,
      "weight_kg": 1416.8,
      "piece_count": 7,
      "packaging_type": "unknown",
      "longest_side_cm": 170,
      "explicit_pallet_count": null,
      "is_stackable": null,
      "address_type": "commercial",
      "requires_liftgate": false,
      "requires_pallet_jack": false,
      "requires_appointment": false,
      "detention_minutes": 0,
      "missing_fields": [],
      "confidence": 88,
      "extraction_notes": "parsed"
    }
    """

    draft = extract_quote_draft("ignored", FakeAIClient(content))

    assert draft.postal_code == "T0B 3L0"
    assert draft.city == "New Norway"
    assert draft.cbm == Decimal("6.275")
    assert draft.missing_fields == []


def test_extract_quote_draft_sanitizes_loose_model_json() -> None:
    content = """
    {
      "address_line": "205 Main Street",
      "postal_code": "T0B 3L0",
      "city": "New Norway",
      "province": "AB",
      "cbm": 2.071,
      "weight_kg": 409.8,
      "piece_count": "1",
      "packaging_type": "unknown",
      "longest_side_cm": 170,
      "explicit_pallet_count": null,
      "is_stackable": null,
      "address_type": "commercial",
      "requires_liftgate": null,
      "requires_pallet_jack": null,
      "requires_appointment": null,
      "detention_minutes": null,
      "missing_fields": null,
      "confidence": "high",
      "extraction_notes": "parsed"
    }
    """

    draft = extract_quote_draft("ignored", FakeAIClient(content))

    assert draft.confidence == 85
    assert draft.requires_liftgate is False
    assert draft.requires_pallet_jack is False
    assert draft.requires_appointment is False
    assert draft.detention_minutes == 0
    assert draft.piece_count == 1
    assert draft.missing_fields == []


def test_extract_quote_draft_ignores_non_blocking_model_missing_fields() -> None:
    content = """
    {
      "address_line": "1055 Flagship Way, unit A",
      "postal_code": "L1X 0P2",
      "city": "Pickering",
      "province": "ON",
      "cbm": 11.7,
      "weight_kg": 1367,
      "piece_count": 99,
      "packaging_type": "carton",
      "longest_side_cm": null,
      "explicit_pallet_count": null,
      "is_stackable": null,
      "address_type": "commercial",
      "requires_liftgate": false,
      "requires_pallet_jack": false,
      "requires_appointment": false,
      "detention_minutes": 0,
      "missing_fields": ["longest_side_cm", "explicit_pallet_count", "is_stackable"],
      "confidence": 86,
      "extraction_notes": "aggregate cargo details"
    }
    """

    draft = extract_quote_draft("ignored", FakeAIClient(content))

    assert draft.missing_fields == []
