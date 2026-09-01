"""需求管理接口：查看/创建/状态变更（写回 requirements/ 文件）。"""
from fastapi import APIRouter, HTTPException

from ..schemas.requirement import RequirementCreate, RequirementOut, RequirementUpdate
from ..services.requirements_service import (
    RequirementError,
    create_requirement,
    get_requirement,
    list_requirements,
    update_status,
)

router = APIRouter()


@router.get("", response_model=list[RequirementOut])
def list_reqs():
    return list_requirements()


@router.get("/{rid}", response_model=dict)
def get_req(rid: str):
    try:
        return get_requirement(rid)
    except RequirementError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("", response_model=RequirementOut)
def create_req(payload: RequirementCreate):
    return create_requirement(payload.title, payload.summary)


@router.patch("/{rid}", response_model=RequirementOut)
def update_req(rid: str, payload: RequirementUpdate):
    try:
        return update_status(rid, payload.status)
    except RequirementError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
