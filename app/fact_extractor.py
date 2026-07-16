import re


def extract_sheet_facts(text: str) -> dict:
    """
    Extract important engineering sheet facts from PDF text.
    """

    upper_text = text.upper()

    # More robust station extraction.
    # Finds patterns like STA. 3194+64.11 and also standalone 3194+64.11.
    station_matches = re.findall(
        r"(?:STA\.?\s*)?([0-9]{2,5}\+[0-9]{2}(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )

    elevation_matches = re.findall(
        r"EL\.?\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )

    top_of_bank_matches = re.findall(
        r"TOB\s+EL\.?\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )

    bottom_matches = re.findall(
        r"BTM\s+EL\.?\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )

    decimal_slope_matches = re.findall(
        r"\b0\.[0-9]{2}\b",
        text,
    )

    # Extract possible side slopes like 1:3, but filter out timestamps like 1:41.
    raw_side_slope_matches = re.findall(
        r"\b[0-9]+:[0-9]+\b",
        text,
    )

    side_slope_matches = []

    for label in raw_side_slope_matches:
        vertical, horizontal = label.split(":")
        vertical_value = int(vertical)
        horizontal_value = int(horizontal)

        # Keep realistic civil side slopes only.
        # Examples: 1:2, 1:3, 1:4, 2:1, 3:1, 4:1.
        # Reject timestamps like 1:41 or 41:01.
        if 1 <= vertical_value <= 4 and 1 <= horizontal_value <= 10:
            side_slope_matches.append(label)

    financial_project_ids = re.findall(
        r"\b[0-9]{6}-[0-9]-[0-9]{2}-[0-9]{2}\b",
        text,
    )

    return {
        "stations": sorted(set(station_matches)),
        "elevations": sorted(set(elevation_matches), key=float),
        "top_of_bank_elevations": sorted(set(top_of_bank_matches), key=float),
        "bottom_elevations": sorted(set(bottom_matches), key=float),
        "decimal_slopes": sorted(set(decimal_slope_matches), key=float),
        "side_slopes": sorted(set(side_slope_matches)),
        "financial_project_ids": sorted(set(financial_project_ids)),
        "has_not_for_construction_note": "NOT FOR CONSTRUCTION" in upper_text,
        "has_revision_block": "REVISIONS" in upper_text,
        "has_cross_section_title": "CROSS SECTION" in upper_text,
        "has_pond_title": "POND UNDER MILITARY BRIDGE" in upper_text,
    }
