"""投诉工单接口：受理客户投诉，覆盖认领工单、提交处置、回访归档与回访清单查询。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.complaint import ComplaintService

router = APIRouter(prefix="/api/complaint", tags=["投诉工单"])

service = ComplaintService()

LIST_FIELDS = ["工单编号", "客户号码", "投诉类型", "投诉内容", "受理时间", "责任班组", "工单状态"]
STATUSES = ["待处置", "处置中", "待回访", "已归档"]


@router.get("/stats")
def stats() -> dict[str, Any]:
    """各状态工单量与待回访任务量，供页头卡片使用。"""
    return service.stats()


@router.get("/callbacks")
def list_callbacks(status: str | None = Query(default=None, description="待回访、已回访")) -> dict[str, Any]:
    """客服工作台待回访清单；与单条工单的回访状态读的是同一份数据。"""
    items = service.list_callbacks(status=status)
    return {"items": items, "total": len(items)}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出投诉工单清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "complaint", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工单编号或客户号码检索"),
    status: str | None = Query(default=None, description="待处置、处置中、待回访、已归档"),
    team: str | None = Query(default=None, description="按责任班组过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、状态与责任班组过滤投诉工单列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, team=team, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条投诉工单明细；跨班组只能看，改单走动作接口并校验授权。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"投诉工单 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/callback", response_model=dict)
def get_entry_callback(entry_id: int) -> dict:
    """另一个回访状态入口：按工单读回访记录，与客服工作台清单同源。"""
    record = service.get_callback_for_entry(entry_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"工单 {entry_id} 还没有生成回访记录")
    return record


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """受理一条客户投诉；同号码当日重复来电自动并单，缺字段时说明原因。"""
    entry, missing, message = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=message or "投诉工单受理失败")
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条工单执行认领工单、提交处置、回访归档；越权或逆序操作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
