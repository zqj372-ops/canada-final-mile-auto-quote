"""Explicit service facts; omission and ambiguous mentions remain unknown."""
import re

SERVICE_FIELDS = ("requires_liftgate", "requires_pallet_jack", "requires_appointment")
_NAMES = {
    "requires_liftgate": r"(?:尾板|lift\s*gate|tail\s*gate|tail\s*lift|requires_liftgate)",
    "requires_pallet_jack": r"(?:手叉车|地牛|pallet\s*jack|requires_pallet_jack)",
    "requires_appointment": r"(?:预约|appointment|requires_appointment)",
}
_BOOL = {"是": True, "需要": True, "yes": True, "true": True, "1": True,
         "否": False, "不需要": False, "no": False, "false": False, "0": False}


def explicit_service_requirements(message: str) -> dict[str, bool | None]:
    facts = {}
    for field, name in _NAMES.items():
        uncertain = any(re.search(name, clause, re.I) and re.search(
            r"是否|需不需要|要不要|不确定|待确认|unknown|maybe|tbd|[?？]", clause, re.I
        ) for clause in re.split(r"[\n,，;；。]", message))
        if uncertain:
            facts[field] = None
            continue
        labelled = re.findall(rf"{name}\s*[:：=]\s*(不需要|需要|true|false|yes|no|是|否|1|0)(?!\w)", message, re.I)
        values = {_BOOL[value.lower()] for value in labelled}
        negative_pattern = rf"(?:不需要|不需|无需|不要)\s*{name}|\b(?:no|without)\s+{name}\b|{name}\s+(?:is\s+)?not\s+(?:needed|required)"
        negative = re.search(negative_pattern, message, re.I)
        positive = re.search(rf"(?<![不无需])(?:需要|需|要)\s*{name}|\bwith\s+{name}\b|{name}\s+(?:is\s+)?(?:needed|required)\b", re.sub(negative_pattern, " ", message, flags=re.I), re.I)
        if negative:
            values.add(False)
        if positive:
            values.add(True)
        facts[field] = next(iter(values)) if len(values) == 1 else None
    return facts
