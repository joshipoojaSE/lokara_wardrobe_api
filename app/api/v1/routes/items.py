from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile, status

from app.api.deps import AnalysisRunnerDep, ItemServiceDep
from app.schemas.answer import ItemSearchResponse
from app.schemas.item import ItemRead, ItemUpdate
from app.storage.base import ImageUpload

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(
    service: ItemServiceDep,
    background_tasks: BackgroundTasks,
    run_analysis: AnalysisRunnerDep,
    images: Annotated[list[UploadFile], File(description="One or more image files.")],
) -> ItemRead:
    """multipart/form-data carrying the image files and nothing else.

    The item is created undescribed — name, category and the rest come back null
    and are filled in with PATCH.

    Once the images are in S3 the response is returned immediately with
    `analysis_status="pending"`, and a background task runs the OpenAI vision
    analysis. Poll GET /items/{id} until the status turns `ready` (or `failed`)
    to pick up the `analysis` object.
    """
    uploads = [
        ImageUpload(
            filename=image.filename or "",
            content_type=image.content_type or "",
            data=await image.read(),
        )
        for image in images
        if image.filename
    ]
    item = await service.create_item(uploads)
    if item.analysis_status == "pending":
        background_tasks.add_task(run_analysis, item.id)
    return item


@router.get("", response_model=list[ItemRead])
async def list_items(
    service: ItemServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
) -> list[ItemRead]:
    return await service.list_items(limit=limit, offset=offset, category=category)


# Declared before /{item_id} on purpose: that path is typed UUID, so a request
# for /items/search landing there would 422 instead of routing here. FastAPI
# matches in declaration order.
@router.get("/search", response_model=ItemSearchResponse)
async def search_items(
    service: ItemServiceDep,
    q: str = Query(min_length=1, description="Natural-language query."),
) -> ItemSearchResponse:
    """Ask about the wardrobe in plain language and get a styled reply.

    Two steps. The query is embedded and compared against each item's stored
    analysis vector, so "something in green" reaches a mint tee whether or not
    the words line up. The closest items are then described to a language model,
    which decides which are actually worth showing and writes the `reason` on
    each one.

    `items` holds only what the model picked — never the raw ranking, which
    always returns its nearest rows whether or not they answer the question.
    Each entry carries what a result card needs: `item_id`, `title`,
    `image_url` and `reason`. Call `GET /items/{item_id}` for the full record.

    **Read `has_match` before rendering.** `false` means the wardrobe does not
    contain what was asked for and the reply is offering the closest thing
    instead — show it as a miss, not a hit. `items` may be empty, with `answer`
    explaining why.

    Only items whose analysis is `ready` *and* carries an embedding can be
    found. Costs two model calls: one to embed the query, one to answer.
    """
    return await service.answer_search(q)


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(item_id: UUID, service: ItemServiceDep) -> ItemRead:
    return await service.get_item(item_id)


@router.patch("/{item_id}", response_model=ItemRead)
async def update_item(
    item_id: UUID, payload: ItemUpdate, service: ItemServiceDep
) -> ItemRead:
    return await service.update_item(item_id, payload)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, service: ItemServiceDep) -> None:
    await service.delete_item(item_id)
