from app.schemas.analysis import ItemAnalysisResult

# The 29 analysis fields in prompt order, paired with the label each one gets in
# the embedded text. `id`, `item_id` and the timestamps are deliberately absent:
# a UUID and a creation date carry no meaning about the garment, and embedding
# them pushes every item apart on tokens that are unique by construction.
_FIELDS: tuple[tuple[str, str], ...] = (
    ("Title", "title"),
    ("Type", "type"),
    ("Category", "category"),
    ("Brand", "brand_guess"),
    ("Colors", "colors_hex"),
    ("Color family", "color_family"),
    ("Material", "material"),
    ("Fabric weight", "fabric_weight"),
    ("Fit", "fit"),
    ("Cut", "cut"),
    ("Silhouette match", "silhouette_match"),
    ("Pattern", "pattern"),
    ("Print position", "print_position"),
    ("Sleeve length", "sleeve_length"),
    ("Neckline", "neckline"),
    ("Length", "length"),
    ("Style vibe", "style_vibe"),
    ("Occasion", "occasion"),
    ("Formality score", "formality_score"),
    ("Wardrobe role", "wardrobe_role"),
    ("Visual weight", "visual_weight"),
    ("Season", "season"),
    ("Temperature range", "temperature_range"),
    ("Layering", "layering_suggestion"),
    ("Separability", "separability"),
    ("Harmonizing colors", "harmonizing_colors_hex"),
    ("Harmonizing families", "harmonizing_families"),
    ("Pairs with", "pairing_suggestions"),
    ("Tags", "tags"),
)


def analysis_to_text(result: ItemAnalysisResult) -> str:
    """Render one analysis as the text that gets embedded.

    The field order is fixed by `_FIELDS` rather than taken from the model dump,
    because the same analysis must always produce byte-identical text: a
    re-analysis that reordered fields would move the item in vector space for no
    reason the wardrobe can see.
    """
    lines = []
    for label, field in _FIELDS:
        value = getattr(result, field)
        if value is None:
            # Only `brand_guess` is nullable. An absent brand is not the same
            # claim as "Brand: None", so the line is dropped entirely.
            continue
        if isinstance(value, list):
            value = ", ".join(str(entry) for entry in value)
        lines.append(f"{label}: {value}")
    return "\n".join(lines)
