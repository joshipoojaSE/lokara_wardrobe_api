from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile, status

from app.api.deps import AnalysisRunnerDep, ItemServiceDep
from app.schemas.item import ItemRead, ItemSearchResult, ItemUpdate
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
@router.get("/search", response_model=list[ItemSearchResult])
async def search_items(
    service: ItemServiceDep,
    q: str = Query(min_length=1, description="Natural-language query."),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ItemSearchResult]:
    """Find items by meaning rather than by exact field match.

    The query is embedded and compared against each item's stored analysis
    vector, so "I want a red tshirt" matches a crimson tee whether or not the
    words line up. Results come back closest-first with a `score` of
    `1 - cosine distance`.

    Only items whose analysis is `ready` *and* carries an embedding can match.
    """
    return await service.search_items(q, limit=limit, offset=offset)


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
