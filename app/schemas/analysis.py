from typing import Literal

from pydantic import BaseModel, ConfigDict

# The 21 parent families the prompt maps every hex code onto.
ColorFamily = Literal[
    "Red", "Maroon", "Pink", "Orange", "Yellow", "Mustard", "Green", "Olive",
    "Teal", "Blue", "Navy", "Purple", "Lavender", "White", "Ivory", "Beige",
    "Brown", "Grey", "Black", "Gold", "Silver",
]


class ItemAnalysisResult(BaseModel):
    """The 29 fields the vision prompt returns, in prompt order.

    Doubles as the JSON schema handed to `messages.parse()` and as the read
    schema for the stored row, so field names match `ItemAnalysis` exactly.
    Nullable fields are declared `| None` without a default: still required in
    the generated schema, so the model must answer rather than omit.
    """

    model_config = ConfigDict(from_attributes=True)

    title: str
    type: Literal["Top", "Bottom", "Dress", "Outerwear", "Footwear", "Accessory"]
    category: str
    brand_guess: str | None
    colors_hex: list[str]
    color_family: ColorFamily
    material: str
    fabric_weight: Literal["Light", "Medium", "Stiff"]
    fit: str
    cut: Literal["Straight", "A-line", "Fitted", "Boxy"]
    silhouette_match: str
    pattern: str
    print_position: Literal["Top", "Bottom", "All-over", "N/A"]
    sleeve_length: str
    neckline: Literal["Round", "V", "Square", "Polo", "Turtleneck", "Hooded", "N/A"]
    length: Literal["Short", "Mid", "Long"]
    style_vibe: str
    occasion: Literal["Casual", "Office", "Party", "Festive", "Daily Wear"]
    formality_score: int
    wardrobe_role: Literal["Statement", "Basic", "Accessory"]
    visual_weight: Literal["Light", "Medium", "Heavy"]
    season: Literal["Summer", "Winter", "All-season"]
    temperature_range: str
    layering_suggestion: Literal["Inner layer", "Outer layer", "Standalone"]
    separability: Literal["Single Unit", "Separable Set"]
    harmonizing_colors_hex: list[str]
    harmonizing_families: list[ColorFamily]
    pairing_suggestions: list[str]
    tags: list[str]
