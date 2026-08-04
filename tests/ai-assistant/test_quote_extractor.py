from decimal import Decimal

import pytest

from packages.ai_assistant.model_client import AIResponse
from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft,
    apply_deterministic_extraction,
    extract_quote_draft,
    extract_quote_draft_with_agents,
)


class FakeAIClient:
    def __init__(self, content: str):
        self.content = content

    def complete(self, _messages: object) -> AIResponse:
        return AIResponse(content=self.content)


class FakeDualAIClient:
    def __init__(self, *, cargo: str, address: str):
        self.cargo = cargo
        self.address = address

    def complete(self, messages: object) -> AIResponse:
        first = messages[0].content if isinstance(messages, list) and messages else ""
        return AIResponse(content=self.cargo if "货物字段 Agent" in first else self.address)


class RepairingDualAIClient(FakeDualAIClient):
    def __init__(self, *, cargo: str, address: str):
        super().__init__(cargo=cargo, address=address)
        self.cargo_calls = 0

    def complete(self, messages: object) -> AIResponse:
        first = messages[0].content if isinstance(messages, list) and messages else ""
        if "货物字段 Agent" not in first:
            return AIResponse(content=self.address)
        self.cargo_calls += 1
        return AIResponse(content="not json" if self.cargo_calls == 1 else self.cargo)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "NO. OF PACKAGES: 18 / TOTAL GROSS WT: 1,234.5 KGS / VOLUME: 12.75 CBM",
            {"piece_count": 18, "weight_kg": Decimal("1234.5"), "cbm": Decimal("12.750")},
        ),
        (
            "CTNS: 20 | G/W: 1,100 KG | C.B.M.: 3.84",
            {"piece_count": 20, "weight_kg": Decimal("1100.0"), "cbm": Decimal("3.840")},
        ),
        (
            "20箱，单箱毛重55公斤，共计3.84方",
            {"piece_count": 20, "weight_kg": Decimal("1100.0"), "cbm": Decimal("3.840")},
        ),
        (
            "20 cartons @ 55 kg each; total volume 3.84 m3",
            {"piece_count": 20, "weight_kg": Decimal("1100.0"), "cbm": Decimal("3.840")},
        ),
        (
            "2 skids / gross weight 900 lbs / volume 120 cu ft",
            {
                "piece_count": 2,
                "weight_kg": Decimal("408.2"),
                "cbm": Decimal("3.398"),
                "packaging_type": "pallet",
            },
        ),
        (
            "10 crates, G.W. 2.5 MT, MEAS 18.2 CBM",
            {
                "piece_count": 10,
                "weight_kg": Decimal("2500.0"),
                "cbm": Decimal("18.200"),
                "packaging_type": "wooden_crate",
            },
        ),
        (
            "QTY 12 PKGS; GW 1250,5 KG; VOL 8,75 CBM",
            {"piece_count": 12, "weight_kg": Decimal("1250.5"), "cbm": Decimal("8.750")},
        ),
        (
            "QTY: 2 PLTS; L/W/H: 120/80/150 CM; G.W.: 1,000 KG",
            {
                "piece_count": 2,
                "weight_kg": Decimal("1000.0"),
                "cbm": Decimal("2.880"),
                "dimensions": (Decimal("120.0"), Decimal("80.0"), Decimal("150.0")),
            },
        ),
        (
            "2 @ 48 x 40 x 60 in, total weight 900 lbs",
            {
                "piece_count": 2,
                "weight_kg": Decimal("408.2"),
                "cbm": Decimal("3.776"),
                "dimensions": (Decimal("121.9"), Decimal("101.6"), Decimal("152.4")),
            },
        ),
        (
            "48x40x60IN / 2 PLTS / GW 900LBS",
            {
                "piece_count": 2,
                "weight_kg": Decimal("408.2"),
                "cbm": Decimal("3.776"),
            },
        ),
        (
            "2 PCS 1200 x 800 x 1500 MMS, gross wt 1000 KGS",
            {
                "piece_count": 2,
                "weight_kg": Decimal("1000.0"),
                "cbm": Decimal("2.880"),
                "dimensions": (Decimal("120.0"), Decimal("80.0"), Decimal("150.0")),
            },
        ),
        (
            "W:80cm H:150cm L:120cm, QTY 2, total weight 1000kg",
            {
                "piece_count": 2,
                "weight_kg": Decimal("1000.0"),
                "cbm": Decimal("2.880"),
                "dimensions": (Decimal("120.0"), Decimal("80.0"), Decimal("150.0")),
            },
        ),
        (
            "3 CASES\nDIMENSIONS EACH: 40\"L x 48\"W x 60\"H\nWEIGHT EACH: 200 LBS\nTOTAL CUBE: 120 CFT",
            {"piece_count": 3, "weight_kg": Decimal("272.2"), "cbm": Decimal("5.663")},
        ),
        (
            "12 bundles; 980 kilograms gross; 6.2 cubic metres",
            {"piece_count": 12, "weight_kg": Decimal("980.0"), "cbm": Decimal("6.200")},
        ),
        (
            "PKG COUNT = 6; TOTAL WT = 0.8 T; CUBE = 4.5 M^3",
            {"piece_count": 6, "weight_kg": Decimal("800.0"), "cbm": Decimal("4.500")},
        ),
        (
            "8 ctns, ttl wt 640 kgs, ttl vol 5.6 cbm",
            {"piece_count": 8, "weight_kg": Decimal("640.0"), "cbm": Decimal("5.600")},
        ),
    ],
    ids=[
        "no-of-packages",
        "freight-abbreviations",
        "chinese-per-carton-weight",
        "english-each-weight",
        "imperial-aggregate",
        "metric-ton",
        "decimal-comma",
        "lwh-slash",
        "at-prefix-imperial-dimensions",
        "quantity-between-dimensions-and-weight",
        "plural-mm",
        "unordered-lwh-labels",
        "multiline-each-weight-and-cube",
        "natural-unit-names",
        "compact-field-labels",
        "ttl-labels",
    ],
)
def test_cargo_inquiry_format_corpus(raw: str, expected: dict[str, object]) -> None:
    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    for field in ("piece_count", "weight_kg", "cbm", "packaging_type"):
        if field in expected:
            assert getattr(draft, field) == expected[field]
    if "dimensions" in expected:
        assert draft.cargo_items
        item = draft.cargo_items[0]
        assert (item.length_cm, item.width_cm, item.height_cm) == expected["dimensions"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            """
加拿大地址：6155 rue LaFontaine h1n2b8 Montreal QC Canada h1n2b8
品名：液压剪角机
尺寸：60x36x50cm/68kg*4
55x36x36cm/45kg*4
60x36x50cm/57kg*3
55x36x36cm/38kg*3
总重：1.3cbm 737kg
""",
            {
                "piece_count": 14,
                "weight_kg": Decimal("737.0"),
                "cbm": Decimal("1.255"),
                "quantities": [4, 4, 3, 3],
                "dimensions": [
                    (Decimal("60.0"), Decimal("36.0"), Decimal("50.0")),
                    (Decimal("55.0"), Decimal("36.0"), Decimal("36.0")),
                    (Decimal("60.0"), Decimal("36.0"), Decimal("50.0")),
                    (Decimal("55.0"), Decimal("36.0"), Decimal("36.0")),
                ],
                "weights": [Decimal("68.00"), Decimal("45.00"), Decimal("57.00"), Decimal("38.00")],
                "postal_code": "H1N 2B8",
            },
        ),
        (
            """
地址：27 Arthur Griffin Crescent，Caledon East, Ontario, Canada，L7C 4E9
箱规：3.21*0.27*0.25m*38kg*4
3.17*0.27*0.25*42kg*2
4.13*0.27*0.25*60kg*1
总：296kg1.6cbm 除湿机
""",
            {
                "piece_count": 7,
                "weight_kg": Decimal("296.0"),
                "cbm": Decimal("1.573"),
                "quantities": [4, 2, 1],
                "dimensions": [
                    (Decimal("321.0"), Decimal("27.0"), Decimal("25.0")),
                    (Decimal("317.0"), Decimal("27.0"), Decimal("25.0")),
                    (Decimal("413.0"), Decimal("27.0"), Decimal("25.0")),
                ],
                "weights": [Decimal("38.00"), Decimal("42.00"), Decimal("60.00")],
                "postal_code": "L7C 4E9",
            },
        ),
        (
            """
1595 Sour Springs Rd, Hagersville, Ontario, Canada, N0A 1M0 96x120x70cm 115kg每件 共3件
加拿大海派ddp
345kg =2.42cbm
""",
            {
                "piece_count": 3,
                "weight_kg": Decimal("345.0"),
                "cbm": Decimal("2.419"),
                "quantities": [3],
                "dimensions": [(Decimal("96.0"), Decimal("120.0"), Decimal("70.0"))],
                "weights": [Decimal("115.00")],
                "postal_code": "N0A 1M0",
            },
        ),
    ],
    ids=["weight-times-quantity", "inherited-meter-unit", "each-weight-with-compact-totals"],
)
def test_real_world_compact_cargo_inquiries(raw: str, expected: dict[str, object]) -> None:
    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == expected["piece_count"]
    assert draft.weight_kg == expected["weight_kg"]
    assert draft.cbm == expected["cbm"]
    assert draft.postal_code == expected["postal_code"]
    assert [item.quantity for item in draft.cargo_items] == expected["quantities"]
    assert [
        (item.length_cm, item.width_cm, item.height_cm)
        for item in draft.cargo_items
    ] == expected["dimensions"]
    assert [item.weight_kg for item in draft.cargo_items] == expected["weights"]
    assert sum(item.quantity for item in draft.cargo_items) == draft.piece_count


def test_consecutive_cargo_lines_inherit_the_first_dimension_unit() -> None:
    raw = """
    箱规：3.21*1.27*1.25m*38kg*2
    3.17*1.20*1.10*42kg*1
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 3
    assert draft.weight_kg == Decimal("118.0")
    assert [
        (item.length_cm, item.width_cm, item.height_cm)
        for item in draft.cargo_items
    ] == [
        (Decimal("321.0"), Decimal("127.0"), Decimal("125.0")),
        (Decimal("317.0"), Decimal("120.0"), Decimal("110.0")),
    ]


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
    assert draft.cbm == Decimal("2.123")
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


def test_deterministic_extraction_preserves_aggregate_only_cargo_as_a_summary_item() -> None:
    raw = """
    QTY: 700 CTNS / G.W.: 2,814 KGS / MEAS: 35 CBM
    Delivery: 100 Industrial Road, Toronto, ON M1B 1A1
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 700
    assert draft.cbm == Decimal("35.000")
    assert draft.weight_kg == Decimal("2814.0")
    assert draft.packaging_type == "carton"
    assert draft.longest_side_cm is None
    assert len(draft.cargo_items) == 1
    summary = draft.cargo_items[0]
    assert summary.quantity == 700
    assert summary.length_cm is None
    assert summary.width_cm is None
    assert summary.height_cm is None
    assert summary.weight_kg == Decimal("4.02")
    assert summary.cbm == Decimal("0.050000")
    assert summary.total_weight_kg == Decimal("2814.0")
    assert summary.total_cbm == Decimal("35")
    assert summary.source_span == "QTY: 700 CTNS / G.W.: 2,814 KGS / MEAS: 35 CBM"


def test_deterministic_extraction_reads_labeled_dimensions_and_package_aliases() -> None:
    raw = """
    QTY=2 PKGS; DIM: L:1,700 W:1,400 H:870 mm; Gross Wt: 800 KG
    285177 Frontier Road, Calgary, AB T1X 0A0
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 2
    assert draft.cbm == Decimal("4.141")
    assert draft.weight_kg == Decimal("800.0")
    assert draft.longest_side_cm == Decimal("170.0")
    assert len(draft.cargo_items) == 1
    item = draft.cargo_items[0]
    assert item.quantity == 2
    assert item.length_cm == Decimal("170.0")
    assert item.width_cm == Decimal("140.0")
    assert item.height_cm == Decimal("87.0")
    assert item.weight_kg == Decimal("400.00")


def test_deterministic_extraction_does_not_treat_labeled_dimensions_as_total_cbm() -> None:
    raw = "数量: 1件; 体积: 1700*1400*870 mm; 重量: 800 KG"

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 1
    assert draft.cbm == Decimal("2.071")
    assert draft.weight_kg == Decimal("800.0")
    assert draft.cargo_items[0].length_cm == Decimal("170.0")


def test_deterministic_extraction_reads_quantity_between_dimensions_and_weight() -> None:
    raw = "DIM: １，７００ ｘ １，４００ ｘ ８７０ ｍｍ / 2 PLTS / G.W. 800 KG"

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 2
    assert draft.explicit_pallet_count == 2
    assert draft.packaging_type == "pallet"
    assert draft.cbm == Decimal("4.141")
    assert draft.weight_kg == Decimal("800.0")
    assert draft.cargo_items[0].quantity == 2
    assert draft.cargo_items[0].weight_kg == Decimal("400.00")


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


def test_deterministic_extraction_prefers_calculated_totals_for_single_carton_spec() -> None:
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
    assert draft.cbm == Decimal("2.092")
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
    assert draft.cbm == Decimal("2.092")
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
    assert draft.cbm == Decimal("3.836")
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
    assert draft.cbm == Decimal("2.722")
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
    assert draft.cbm == Decimal("5.049")
    assert draft.weight_kg == Decimal("1630.0")
    assert draft.longest_side_cm == Decimal("270.0")
    assert len(draft.cargo_items) == 1
    assert draft.cargo_items[0].quantity == 1
    assert draft.cargo_items[0].weight_kg == Decimal("1630.00")


def test_deterministic_extraction_recognizes_chinese_pallet_count() -> None:
    raw = """
    3托盘 120*100*150cm
    总重1200kg 总体积4.5CBM
    285177 Frontier Road
    Calgary AB T1X 0A0
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 3
    assert draft.explicit_pallet_count == 3
    assert draft.weight_kg == Decimal("1200.0")
    assert draft.cbm == Decimal("5.400")
    assert draft.cargo_items[0].quantity == 3
    assert draft.cargo_items[0].weight_kg == Decimal("400.00")


def test_deterministic_extraction_calculates_pallet_volume_and_weight_expression() -> None:
    raw = """
    3cbm，2个托盘，120x100x125cm
    毛重：785公斤+800kg=1585kgs
    到门地址:1729 chemin de château-bigot, Québec (Québec) Canada G2L 1H4
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "1729 chemin de château-bigot"
    assert draft.postal_code == "G2L 1H4"
    assert draft.province == "QC"
    assert draft.packaging_type == "pallet"
    assert draft.explicit_pallet_count == 2
    assert draft.piece_count == 2
    assert draft.cbm == Decimal("3.000")
    assert draft.weight_kg == Decimal("1585.0")
    assert [item.quantity for item in draft.cargo_items] == [1, 1]
    assert [item.weight_kg for item in draft.cargo_items] == [
        Decimal("785.00"),
        Decimal("800.00"),
    ]
    assert [item.cbm for item in draft.cargo_items] == [
        Decimal("1.500000"),
        Decimal("1.500000"),
    ]
    assert "calculated_cbm_from_dimensions" in draft.validation_notes
    assert "calculated_weight_from_arithmetic" in draft.validation_notes


def test_deterministic_extraction_replaces_incorrect_declared_cargo_totals() -> None:
    raw = """
    4cbm，2个托盘，120x100x125cm
    毛重：785公斤+800kg=9999kgs
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.piece_count == 2
    assert draft.cbm == Decimal("3.000")
    assert draft.weight_kg == Decimal("1585.0")
    assert "declared_cbm_mismatch:declared=4.000,calculated=3.000" in draft.validation_notes
    assert "declared_weight_mismatch:declared=9999.0,calculated=1585.0" in draft.validation_notes


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


def test_deterministic_extraction_splits_total_weight_for_aggregate_carton_line() -> None:
    raw = """
    720072 Range Road 84 Wembley, Alberta
    T0H3S0 Canada,
    200箱, 2270kgs, 10.9cbm 50*50*21.8cm
    """

    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), raw)

    assert draft.address_line == "720072 Range Road 84"
    assert draft.city == "Wembley"
    assert draft.province == "AB"
    assert draft.postal_code == "T0H 3S0"
    assert draft.piece_count == 200
    assert draft.cbm == Decimal("10.900")
    assert draft.weight_kg == Decimal("2270.0")
    assert len(draft.cargo_items) == 1
    assert draft.cargo_items[0].quantity == 200
    assert draft.cargo_items[0].length_cm == Decimal("50.0")
    assert draft.cargo_items[0].width_cm == Decimal("50.0")
    assert draft.cargo_items[0].height_cm == Decimal("21.8")
    assert draft.cargo_items[0].weight_kg == Decimal("11.35")


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


def test_extract_quote_draft_with_agents_merges_cargo_and_address_outputs() -> None:
    cargo = """
    {
      "cbm": 10.9,
      "weight_kg": 2270,
      "piece_count": 200,
      "packaging_type": "carton",
      "longest_side_cm": 50,
      "explicit_pallet_count": null,
      "is_stackable": null,
      "cargo_items": [
        {
          "quantity": 200,
          "length_cm": 50,
          "width_cm": 50,
          "height_cm": 21.8,
          "weight_kg": 2270,
          "cbm": 0.054,
          "total_weight_kg": 2270,
          "total_cbm": 10.9,
          "source_span": "200箱, 2270kgs, 10.9cbm 50*50*21.8cm"
        }
      ],
      "missing_fields": [],
      "confidence": 86,
      "extraction_notes": "cargo parsed"
    }
    """
    address = """
    {
      "address_line": "720072 Range Road 84",
      "postal_code": "T0H3S0",
      "city": "Wembley",
      "province": "Alberta",
      "country": "Canada",
      "address_type": "commercial",
      "requires_liftgate": false,
      "requires_pallet_jack": false,
      "requires_appointment": false,
      "detention_minutes": 0,
      "missing_fields": [],
      "confidence": 88,
      "extraction_notes": "address parsed"
    }
    """
    raw = """
    720072 Range Road 84 Wembley, Alberta
    T0H3S0 Canada,
    200箱, 2270kgs, 10.9cbm 50*50*21.8cm
    """

    draft = extract_quote_draft_with_agents(raw, FakeDualAIClient(cargo=cargo, address=address))

    assert draft.address_line == "720072 Range Road 84"
    assert draft.city == "Wembley"
    assert draft.province == "AB"
    assert draft.postal_code == "T0H 3S0"
    assert draft.piece_count == 200
    assert draft.cbm == Decimal("10.9")
    assert draft.weight_kg == Decimal("2270")
    assert draft.cargo_items[0].quantity == 200
    assert draft.cargo_items[0].weight_kg == Decimal("11.35")
    assert "calculated_weight_from_cargo_items" in draft.validation_notes


def test_extract_quote_draft_with_agents_recalculates_copied_cargo_totals() -> None:
    cargo = """
    {
      "cbm": 4,
      "weight_kg": 9999,
      "piece_count": 2,
      "packaging_type": "pallet",
      "longest_side_cm": 125,
      "explicit_pallet_count": 2,
      "is_stackable": null,
      "cargo_items": [{
        "quantity": 2,
        "length_cm": 120,
        "width_cm": 100,
        "height_cm": 125,
        "weight_kg": 4999.5,
        "cbm": 2,
        "total_weight_kg": 9999,
        "total_cbm": 4,
        "source_span": "4cbm，2个托盘，120x100x125cm"
      }],
      "missing_fields": [],
      "confidence": 90,
      "extraction_notes": "copied the declared totals"
    }
    """
    address = """
    {
      "address_line": "1729 chemin de château-bigot",
      "postal_code": "G2L1H4",
      "city": "Québec",
      "province": "Québec",
      "country": "Canada",
      "address_type": "commercial",
      "requires_liftgate": false,
      "requires_pallet_jack": false,
      "requires_appointment": false,
      "detention_minutes": 0,
      "missing_fields": [],
      "confidence": 90,
      "extraction_notes": "address parsed"
    }
    """
    raw = """
    4cbm，2个托盘，120x100x125cm
    毛重：785公斤+800kg=9999kgs
    到门地址:1729 chemin de château-bigot, Québec (Québec) Canada G2L 1H4
    """

    draft = extract_quote_draft_with_agents(raw, FakeDualAIClient(cargo=cargo, address=address))

    assert draft.piece_count == 2
    assert draft.cbm == Decimal("3.000")
    assert draft.weight_kg == Decimal("1585.0")
    assert [item.weight_kg for item in draft.cargo_items] == [
        Decimal("785.00"),
        Decimal("800.00"),
    ]
    assert "declared_cbm_mismatch:declared=4.000,calculated=3.000" in draft.validation_notes
    assert "declared_weight_mismatch:declared=9999.0,calculated=1585.0" in draft.validation_notes


def test_extract_quote_draft_with_agents_repairs_invalid_json_once() -> None:
    cargo = """
    {
      "cbm": 2.18,
      "weight_kg": 352.5,
      "piece_count": 15,
      "packaging_type": "carton",
      "longest_side_cm": 62.5,
      "explicit_pallet_count": null,
      "is_stackable": null,
      "cargo_items": [],
      "missing_fields": [],
      "confidence": 90,
      "extraction_notes": "repaired"
    }
    """
    address = """
    {
      "address_line": "9699 Sills Ave #8",
      "postal_code": "V6Y 0C8",
      "city": "Richmond",
      "province": "BC",
      "country": "Canada",
      "address_type": "commercial",
      "requires_liftgate": false,
      "requires_pallet_jack": false,
      "requires_appointment": false,
      "detention_minutes": 0,
      "missing_fields": [],
      "confidence": 90,
      "extraction_notes": "parsed"
    }
    """
    client = RepairingDualAIClient(cargo=cargo, address=address)

    draft = extract_quote_draft_with_agents(
        "15箱 合计352.5kg 2.18CBM\n9699 Sills Ave #8, Richmond, BC V6Y 0C8",
        client,
    )

    assert client.cargo_calls == 2
    assert draft.piece_count == 15
    assert draft.weight_kg == Decimal("352.5")
    assert draft.postal_code == "V6Y 0C8"
    assert len(draft.cargo_items) == 1
    summary = draft.cargo_items[0]
    assert summary.quantity == 15
    assert summary.length_cm is None
    assert summary.width_cm is None
    assert summary.height_cm is None
    assert summary.weight_kg == Decimal("23.50")
    assert summary.cbm == Decimal("0.145333")
    assert summary.total_weight_kg == Decimal("352.5")
    assert summary.total_cbm == Decimal("2.18")


def test_extract_quote_draft_with_agents_prefers_explicit_and_confirmed_fields() -> None:
    cargo = """
    {
      "cbm": 5.1,
      "weight_kg": 999,
      "piece_count": 1630,
      "packaging_type": "unknown",
      "longest_side_cm": 270,
      "explicit_pallet_count": null,
      "is_stackable": null,
      "cargo_items": [{
        "quantity": 1630,
        "length_cm": 270,
        "width_cm": 110,
        "height_cm": 170,
        "weight_kg": 1,
        "cbm": 5.049,
        "total_weight_kg": 999,
        "total_cbm": 5.1,
        "source_span": "总重：1630KG"
      }],
      "missing_fields": [],
      "confidence": 88,
      "extraction_notes": "model confused weight with quantity"
    }
    """
    address = """
    {
      "address_line": "436 route 275",
      "postal_code": "G0S2X0",
      "city": "Sainte-Marguerite de dorchester",
      "province": "Québec",
      "country": "Canada",
      "address_type": "residential",
      "requires_liftgate": true,
      "requires_pallet_jack": true,
      "requires_appointment": true,
      "detention_minutes": 30,
      "missing_fields": [],
      "confidence": 88,
      "extraction_notes": "guessed"
    }
    """
    raw = """
    数量：共1件
    体积重量：2700*1100*1700mm 5.1CBM
    总重：1630KG
    地址：436 route 275
    Sainte-Marguerite de dorchester Québec Canada G0S2X0

    ---
    前台已确认字段，仅用于字段提取，不允许 AI 计算价格：
    address_type=commercial
    requires_liftgate=false
    requires_pallet_jack=false
    requires_appointment=false
    detention_minutes=0
    """

    draft = extract_quote_draft_with_agents(raw, FakeDualAIClient(cargo=cargo, address=address))

    assert draft.piece_count == 1
    assert draft.weight_kg == Decimal("1630.0")
    assert draft.cargo_items[0].quantity == 1
    assert draft.cargo_items[0].weight_kg == Decimal("1630.00")
    assert draft.address_type == "commercial"
    assert draft.requires_liftgate is False
    assert draft.requires_pallet_jack is False
    assert draft.requires_appointment is False
    assert draft.detention_minutes == 0
    assert "explicit_source_override:piece_count,weight_kg,confirmed_fields" in draft.validation_notes
