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


def select_window(
    hits: Sequence[ItemSearchResult], limit: int
) -> list[ItemSearchResult]:
    """Choose which retrieved hits the model gets to see, across garment types.

    A plain `hits[:limit]` is the wrong window for an outfit question. One query
    vector ranks the whole wardrobe by one notion of closeness, so "what goes
    with my white shirt" fills every slot with shirts and the bottoms the answer
    needs never reach the prompt. The model then has nothing to pair the shirt
    with and falls back on the anchor item's `Pairs with` line — garment types
    the shopper may not own.

    So the window is filled round-robin over `analysis.type`: the closest Top,
    then the closest Bottom, then the closest Footwear, and around again. Groups
    are visited in order of their best hit, and each group is drained in score
    order, so the strongest match in the wardrobe is always position 1.

    The cost is honest: a wholly irrelevant Accessory can displace a third
    relevant Top. That is the trade an outfit needs, and the similarity score
    travels with every entry, so the model can still see a filler row for what
    it is and leave it unpicked.

    A single-type wardrobe degenerates to `hits[:limit]` exactly. The result is
    always a subsequence of `hits`, so it stays closest-first and the numbering
    `hits_to_context` hands the model still runs down the ranking.
    """
    if limit <= 0:
        return []

    # Insertion order is first appearance, which is each type's best hit.
    groups: dict[str, list[int]] = {}
    for index, hit in enumerate(hits):
        # Search joins through the analysis row, so a hit always carries one.
        key = hit.item.analysis.type if hit.item.analysis else ""
        groups.setdefault(key, []).append(index)

    chosen: set[int] = set()
    for depth in range(max((len(group) for group in groups.values()), default=0)):
        for group in groups.values():
            if depth < len(group):
                chosen.add(group[depth])
                if len(chosen) == limit:
                    return [hit for i, hit in enumerate(hits) if i in chosen]
    return [hit for i, hit in enumerate(hits) if i in chosen]
