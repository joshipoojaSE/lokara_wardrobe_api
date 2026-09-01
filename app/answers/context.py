from collections.abc import Sequence

from app.answers.prompt import EMPTY_WARDROBE
from app.embeddings.text import analysis_to_text
from app.schemas.item import ItemSearchResult


def hits_to_context(hits: Sequence[ItemSearchResult]) -> str:
    """Render retrieved items as the WARDROBE block of the prompt.

    Numbering is the 1-based position in `hits`, which is what the model cites in
    `picks[].index` — so the caller must pass exactly the slice it intends to map
    back, already trimmed. Nothing is filtered here, or the numbering would drift
    away from the caller's list.

    Reuses `analysis_to_text`, the same renderer that produced the embedding each
    item was retrieved by: the model reads the description the vector was built
    from, not a second, subtly different one.

    The similarity score is included on purpose. It is the model's only signal
    that a low-ranked item may be a near miss rather than a real answer, which is
    what lets it say "you don't own one of those" instead of dressing up the
    closest row as a match.
    """
    if not hits:
        return EMPTY_WARDROBE

    blocks = []
    for position, hit in enumerate(hits, start=1):
        # Search joins through the analysis row, so a hit always carries one.
        body = analysis_to_text(hit.item.analysis) if hit.item.analysis else ""
        blocks.append(f"[{position}] (similarity {hit.score:.2f})\n{body}")
    return "\n\n".join(blocks)
