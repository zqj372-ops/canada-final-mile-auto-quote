from decimal import Decimal

import pytest

from packages.ai_assistant.fast_extractor import try_extract_locally

SAMPLE = """数量: 2托盘
尺寸: 120x100x150 cm
总重: 800 kg
地址: 8888 Keele St
城市: Concord
省份: ON
邮编: L4K 2N2
地址类型: 商业地址
尾板: 否"""


def test_complete_labelled_shipment_preserves_total_not_per_piece_weight():
    result = try_extract_locally(SAMPLE)
    assert result is not None
    assert result.cbm == Decimal("3.600")
    assert result.weight_kg == 800
    assert result.cargo_items[0].weight_kg == 400
    assert result.piece_count == result.explicit_pallet_count == 2
    assert result.requires_liftgate is False
    assert result.city == "Concord"


def test_imperial_dimensions_and_weight_are_converted():
    result = try_extract_locally(SAMPLE.replace("120x100x150 cm", "48x40x60 in").replace("800 kg", "1000 lb"))
    assert result is not None
    assert result.cargo_items[0].length_cm == Decimal("121.9")
    assert result.weight_kg == Decimal("453.6")


@pytest.mark.parametrize("text", [
    SAMPLE + "\n更正：共 4 托盘", SAMPLE + "\n数量: 3托盘",
    SAMPLE + "\n第二票：V6V 1A1", SAMPLE.replace("总重: 800 kg", "总重: 800 kg 或 1000 kg"),
    SAMPLE.replace("数量: 2托盘", "数量: 2托盘和10纸箱"),
    SAMPLE.replace("总重: 800 kg", "每托: 800 kg"),
    SAMPLE + "\n总体积: 10 cbm", SAMPLE.replace("地址类型: 商业地址", "地址类型: 可能是商业地址"),
    SAMPLE.replace("尺寸: 120x100x150 cm", "尺寸: 120x100x150"),
    SAMPLE.replace("尾板: 否", "尾板: 可能不需要"),
    SAMPLE.replace("数量: 2托盘", "数量: 0托盘"),
])
def test_ambiguous_or_unsupported_inputs_defer_to_model(text):
    assert try_extract_locally(text) is None
