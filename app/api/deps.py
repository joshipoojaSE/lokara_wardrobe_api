from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.item import ItemRepository
from app.services.item import ItemService

DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_item_service(session: DbSession) -> ItemService:
    return ItemService(ItemRepository(session))


ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]
