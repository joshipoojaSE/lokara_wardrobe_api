PROMPT_TEXT = """
Analyze this clothing item image and provide a purely JSON response.
Do not include markdown formatting or conversational filler. Just return the raw JSON.

STRICT COLOR LOGIC RULES:

1. "harmonizing_colors_hex": You MUST provide 12 specific hex codes to maximize the "Mix & Match" algorithm potential.
Include:
* 3 Monochromatic (1 light tint, 1 medium shade, 1 dark shade)
* 1 Complementary (The direct opposite)
* 2 Analogous (Immediate neighbors)
* 4 Neutral Balancing (1 White/Ivory, 1 Black/Grey, 1 Tan/Beige, 1 Earthy tone)
* 2 Split-Complementary (The most sophisticated fashion pairings)


2. "harmonizing_families": For EVERY hex code provided in field 26, map it to exactly one of these 21 Parent Families:
[Red, Maroon, Pink, Orange, Yellow, Mustard, Green, Olive, Teal, Blue, Navy, Purple, Lavender, White, Ivory, Beige, Brown, Grey, Black, Gold, Silver].


Fields required:

1. "title": A short, descriptive title. (Exclude gender terms).
2. "type": One of [Top, Bottom, Dress, Outerwear, Footwear, Accessory].
3. "category": Specific item name (e.g., Shirt, Jeans, Kurti, Saree, T-shirt, Chinos).
4. "brand_guess": Guess the brand if logo is visible, else null.
5. "colors_hex": Array of up to 3 dominant colors in Hex format.
6. "color_family": The primary "Bucket" for the dominant color from the 21 families.
7. "material": Estimated fabric type. (e.g., Cotton, Linen, Denim).
8. "fabric_weight": [Light, Medium, Stiff].
9. "fit": The fit of the garment (e.g., Slim Fit, Oversized, Regular).
10. "cut": [Straight, A-line, Fitted, Boxy].
11. "silhouette_match": Recommended fit for the opposite piece to maintain balance.
12. "pattern": Visual pattern (e.g., Solid, Striped, Graphic Print, Checked).
13. "print_position": [Top, Bottom, All-over, N/A].
14. "sleeve_length": (e.g., Short Sleeve, Long Sleeve, Half Sleeve, Sleeveless N/A).
15. "neckline": [Round, V, Square, Polo, Turtleneck, Hooded, or N/A].
16. "length": [Short, Mid, Long].
17. "style_vibe": (e.g., Minimalist, Streetwear, Boho, Formal, Old Money).
18. "occasion": [Casual, Office, Party, Festive, Daily Wear].
19. "formality_score": Rating from 1 to 10.
20. "wardrobe_role": [Statement, Basic, Accessory].
21. "visual_weight": [Light, Medium, Heavy].
22. "season": [Summer, Winter, All-season].
23. "temperature_range": Suitable range (e.g., "18°C - 25°C").
24. "layering_suggestion": [Inner layer, Outer layer, Standalone].
25. "separability": [Single Unit, Separable Set].
26. "harmonizing_colors_hex": The 12-code array described in Rule 1.
27. "harmonizing_families": The 12-family array described in Rule 2.
28. "pairing_suggestions": Array of maximum clothing categories to complete the look.
29. "tags": Array of 3-5 descriptive tags for remaining style details
"""

MULTI_IMAGE_NOTE = (
    "The images above are different views of the SAME clothing item. "
    "Return one JSON object describing that single item."
)
