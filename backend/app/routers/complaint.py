"""客户投诉工单接口。

投诉主档是回访状态的唯一来源：
- /api/complaint/callback  客服工作台「待回访清单」读主档；
- /api/complaint/track     另一处查询入口，读同一份主档，状态必然一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.complaint import ComplaintService, STAGE_ORDER

router = APIRouter(prefix="/api/complaint", tags=["客户投诉"])

service = ComplaintService()

COLUMNS = [
    "工单编号", "来电号码", "投诉类型", "受理时间", "受理人", "责任班组",
    "认领人", "处置结论", "值班长确认人", "回访结论", "回访状态", "当前环节",
]


@router.get("/meta")
def meta() -> dict[str, Any]:
    """返回环节、投诉类型、责任班组与值班身份名册，供前端渲染与切换身份。"""
    return service.meta()


@router.get("", response_model=PageResult[dict])
def list_complaints(
    keyword: str | None = Query(default=None, description="按工单号或来电号码检索"),
    status: str | None = Query(default=None, description="待处置、处置中、待回访、已归档"),
    crew: str | None = Query(default=None, description="责任班组"),
    ctype: str | None = Query(default=None, description="投诉类型：断站/掉话/资费"),
    operator_id: str | None = Query(default=None, description="当前值班工号，用于可写/只读判断"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """投诉工单流水列表；出参带可写与可执行动作标注，跨班组打开只给只读。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_complaints(
        keyword=keyword, status=status, crew=crew, ctype=ctype,
        operator_id=operator_id, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stages")
def stage_counts() -> dict[str, Any]:
    """各环节在途量，做流水看板。"""
    return {"stages": service.stage_counts()}


@router.get("/callback")
def callback_list(
    status: str | None = Query(default="待回访", description="待回访/已回访"),
    keyword: str | None = Query(default=None, description="按工单号或号码检索"),
) -> dict[str, Any]:
    """客服工作台待回访清单：归档回写后这里读到已回访，来源是投诉主档。"""
    return {"items": service.callback_list(status=status, keyword=keyword)}


@router.get("/track")
def track(keyword: str = Query(description="按工单号或号码查询回访状态")) -> dict[str, Any]:
    """另一处入口查回访状态，与待回访清单取同一份主档。"""
    view = service.track(keyword)
    if view is None:
        raise HTTPException(status_code=404, detail=f"未找到与「{keyword}」匹配的投诉工单")
    return view


@router.post("/backfill")
def backfill() -> ActionResult:
    """对存量工单补责任班组归属（幂等，历史结论不回填）。"""
    result = service.backfill_legacies()
    return ActionResult(ok=True, message=(
        f"存量归属补录完成：本次补派 {result['backfilled']} 条，已有归属保留 {result['preserved']} 条，"
        "历史处置/回访结论原样保留"
    ))


@router.get("/{entry_id}", response_model=dict)
def get_complaint(entry_id: int, operator_id: str | None = None) -> dict:
    """单张投诉工单明细（含追加来电与操作流水）。"""
    entry = service.get_complaint(entry_id, operator_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"投诉工单 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def accept_complaint(payload: EntryPayload) -> ActionResult:
    """受理投诉；同号码当天重复来电只并单追加，不另开新单。"""
    values = payload.values
    entry, message, missing, merged = service.accept(values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """认领/填写处置结论/值班长确认/回访归档；越权或越级流转当场驳回并说明缺哪项授权。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message, changed = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=changed, message=message, entry=entry)
