"""Collection endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from atlas.api.deps import CollectionServiceDep, CurrentUser
from atlas.schemas.paper import CollectionRead, CollectionWrite

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=list[CollectionRead])
async def list_collections(
    user: CurrentUser, service: CollectionServiceDep
) -> list[CollectionRead]:
    rows = await service.list_collections(owner=user)
    return [
        CollectionRead(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            paper_count=count,
            created_at=collection.created_at,
        )
        for collection, count in rows
    ]


@router.post("", response_model=CollectionRead, status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionWrite, user: CurrentUser, service: CollectionServiceDep
) -> CollectionRead:
    collection = await service.create(
        owner=user, name=payload.name, description=payload.description
    )
    return CollectionRead(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        paper_count=0,
        created_at=collection.created_at,
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: uuid.UUID, user: CurrentUser, service: CollectionServiceDep
) -> None:
    """Delete a collection. The papers inside it are not deleted."""
    await service.delete(owner=user, collection_id=collection_id)


@router.put("/{collection_id}/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_paper(
    collection_id: uuid.UUID,
    paper_id: uuid.UUID,
    user: CurrentUser,
    service: CollectionServiceDep,
) -> None:
    """Add a paper to a collection. Idempotent — adding it twice is not an error."""
    await service.add_paper(owner=user, collection_id=collection_id, paper_id=paper_id)


@router.delete("/{collection_id}/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_paper(
    collection_id: uuid.UUID,
    paper_id: uuid.UUID,
    user: CurrentUser,
    service: CollectionServiceDep,
) -> None:
    await service.remove_paper(owner=user, collection_id=collection_id, paper_id=paper_id)
