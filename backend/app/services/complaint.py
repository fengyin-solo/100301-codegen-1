"""客户投诉工单业务规则。

一条投诉工单只能沿「待处置 → 处置中 → 待回访 → 已归档」单向流转，规则都收在这里：
- 同号码同一天只认第一次投诉，后续来电并单追加，不另开工单；
- 工单按投诉类型派到责任班组，只有本班组值班人员能认领并填写处置结论；
- 处置结论须经本班组值班长确认才能转待回访，任何环节都不能退回或越级；
- 回访结论随归档回写，客服工作台与另一处查询入口读的是同一份主档；
- 存量工单按受理顺序只补“责任班组”归属，历史处置/回访结论保持原样不回填。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "complaint"

# 工单只能顺着这条链往下走，不允许退回已经走过的环节。
STAGE_ORDER = ["待处置", "处置中", "待回访", "已归档"]

COMPLAINT_TYPES = ["断站", "掉话", "资费"]
# 受理即按投诉类型派定责任班组。
TYPE_CREW = {"断站": "无线班组", "掉话": "无线班组", "资费": "资费班组"}
CREWS = sorted(set(TYPE_CREW.values()))

# 动作 -> (允许的来源环节, 目标环节)；来源与目标相同表示仍停在本环节补录内容。
ACTION_FLOW = {
    "认领": (["待处置"], "处置中"),
    "填写处置结论": (["处置中"], "处置中"),
    "值班长确认": (["处置中"], "待回访"),
    "回访归档": (["待回访"], "已归档"),
}

# 演示用值班身份：工号 -> 姓名/班组/角色。真实项目里换成账号体系。
# 角色取值：客服、客服主管、值班人员、值班长。
ROSTER: dict[str, dict[str, Any]] = {
    "C001": {"姓名": "王客服", "班组": "客服班组", "角色": ["客服"]},
    "C002": {"姓名": "李主管", "班组": "客服班组", "角色": ["客服", "客服主管"]},
    "W001": {"姓名": "张卫", "班组": "无线班组", "角色": ["值班人员"]},
    "W002": {"姓名": "赵班长", "班组": "无线班组", "角色": ["值班长"]},
    "B001": {"姓名": "孙值", "班组": "资费班组", "角色": ["值班人员"]},
    "B002": {"姓名": "周班长", "班组": "资费班组", "角色": ["值班长"]},
}

ACCEPT_REQUIRED = ["来电号码", "投诉类型", "反映内容"]
BACKFILL_TIME = "2026-10-01 00:00"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _day_of(value: Any) -> str:
    return str(value or "").strip()[:10]


class ComplaintService:
    def __init__(self) -> None:
        # 服务装载时对存量归属补录一次；幂等，重复执行不会改动已有归属。
        self.backfill_legacies()

    # ---- 基础读取 ----
    def meta(self) -> dict[str, Any]:
        return {
            "stages": STAGE_ORDER,
            "types": COMPLAINT_TYPES,
            "type_crew": TYPE_CREW,
            "crews": CREWS,
            "roster": [{"工号": k, **v} for k, v in ROSTER.items()],
            "backfill": self.backfill_status(),
        }

    def _staff(self, staff_id: Any) -> dict[str, Any] | None:
        if not staff_id:
            return None
        return ROSTER.get(str(staff_id).strip())

    def list_complaints(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        crew: str | None = None,
        ctype: str | None = None,
        operator_id: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("工单编号", "")) or key in str(row.get("来电号码", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if crew:
            rows = [row for row in rows if row.get("责任班组") == crew]
        if ctype:
            rows = [row for row in rows if row.get("投诉类型") == ctype]
        total = len(rows)
        start = max(page - 1, 0) * size
        staff = self._staff(operator_id)
        items = [self._view(row, staff) for row in rows[start:start + size]]
        return items, total

    def get_complaint(self, entry_id: int, operator_id: str | None = None) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self._view(row, self._staff(operator_id))

    def stage_counts(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        return [
            {"label": stage, "value": sum(1 for row in rows if row.get("status") == stage)}
            for stage in STAGE_ORDER
        ]

    # ---- 受理与同号码当天去重并单 ----
    def accept(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, list[str], bool]:
        """返回 (工单, 说明, 缺失字段, 是否并单)。"""
        staff = self._staff(values.get("operator_id"))
        if staff is None:
            return None, "受理被驳回：未识别的值班工号，缺少「客服」受理授权", [], False
        if "客服" not in staff["角色"]:
            return None, f"受理被驳回：{staff['姓名']} 缺少「客服」受理授权", [], False

        missing = [f for f in ACCEPT_REQUIRED if not str(values.get(f) or "").strip()]
        if missing:
            return None, "", missing, False

        ctype = str(values["投诉类型"]).strip()
        if ctype not in TYPE_CREW:
            return None, f"投诉类型「{ctype}」不在受理范围（断站/掉话/资费）", [], False

        number = str(values["来电号码"]).strip()
        accepted_at = str(values.get("受理时间") or _now()).strip()

        # 同一号码、同一自然日只认第一次投诉；后续来电并入最早那张。
        anchor = self._first_of_day(number, _day_of(accepted_at))
        if anchor is not None:
            call = {
                "序号": len(anchor.setdefault("追加来电", [])) + 1,
                "来电号码": number,
                "来电时间": accepted_at,
                "反映内容": str(values["反映内容"]).strip(),
                "受理人": staff["姓名"],
            }
            anchor["追加来电"].append(call)
            self._log(anchor, anchor["status"], "重复来电并单", staff["姓名"],
                      f"该号码当日已有首诉工单 {anchor['工单编号']}，本次来电只追加记录，不另开新单")
            return self._view(anchor, staff), (
                f"该号码今日已有首诉工单 {anchor['工单编号']}，本次来电已并单追加（第 {call['序号'] + 1} 次来电），不另开新单"
            ), [], True

        rows = store.rows(MODULE)
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "工单编号": f"TS-{accepted_at[:4]}{max((int(row.get('id', 0)) for row in rows), default=0) + 1:04d}",
            "来电号码": number,
            "投诉类型": ctype,
            "反映内容": str(values["反映内容"]).strip(),
            "受理时间": accepted_at,
            "受理人": staff["姓名"],
            "责任班组": TYPE_CREW[ctype],
            "status": "待处置",
            "pending": True,
            "abnormal": False,
            "认领人": None,
            "处置结论": None,
            "处置时间": None,
            "值班长确认人": None,
            "确认时间": None,
            "回访结论": None,
            "回访人": None,
            "回访时间": None,
            "回访状态": "待回访",
            "追加来电": [],
            "操作流水": [],
            "是否存量": False,
            "归属补录": False,
            "历史处置结论": None,
        }
        self._log(entry, "待处置", "客服受理建单", staff["姓名"], f"按投诉类型派至{entry['责任班组']}")
        rows.append(entry)
        return self._view(entry, staff), f"投诉工单已受理，已派至{entry['责任班组']}", [], False

    def _first_of_day(self, number: str, day: str) -> dict[str, Any] | None:
        candidates = [
            row
            for row in store.rows(MODULE)
            if str(row.get("来电号码", "")).strip() == number and _day_of(row.get("受理时间")) == day
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda row: (str(row.get("受理时间")), int(row.get("id", 0))))

    # ---- 环节流转与授权 ----
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """返回 (工单视图, 说明, 是否生效)。不生效即越权/越级/缺结论，当场驳回。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"投诉工单 {entry_id} 不存在", False
        staff = self._staff(values.get("operator_id"))
        stage = str(entry.get("status"))

        if action not in ACTION_FLOW:
            return self._view(entry, staff), f"动作「{action}」不属于投诉工单可执行范围", False
        sources, target = ACTION_FLOW[action]
        if stage not in sources:
            return self._view(entry, staff), (
                f"当前环节「{stage}」不允许执行「{action}」：工单只能沿"
                f"{' → '.join(STAGE_ORDER)} 单向流转，不可退回或越级"
            ), False

        if action == "认领":
            ok, reason = self._authorize_claim(staff, entry)
            if not ok:
                return self._view(entry, staff), reason, False
            entry["认领人"] = staff["姓名"]
            entry["status"] = target
            self._log(entry, target, "认领并开始处置", staff["姓名"])
            return self._view(entry, staff), "已认领，工单进入处置中", True

        if action == "填写处置结论":
            conclusion = str(values.get("处置结论") or "").strip()
            if not conclusion:
                return self._view(entry, staff), "处置结论不能为空", False
            ok, reason = self._authorize_handler(staff, entry)
            if not ok:
                return self._view(entry, staff), reason, False
            entry["处置结论"] = conclusion
            entry["处置时间"] = _now()
            self._log(entry, stage, "提交处置结论", staff["姓名"], conclusion)
            return self._view(entry, staff), "处置结论已记录，待值班长确认", True

        if action == "值班长确认":
            ok, reason = self._authorize_leader(staff, entry)
            if not ok:
                return self._view(entry, staff), reason, False
            if not str(entry.get("处置结论") or "").strip():
                return self._view(entry, staff), "确认被驳回：处置结论尚未填写，不能转待回访", False
            entry["值班长确认人"] = staff["姓名"]
            entry["确认时间"] = _now()
            entry["status"] = target
            entry["pending"] = True
            self._log(entry, target, "值班长确认", staff["姓名"], "处置结论经确认，转客服待回访")
            return self._view(entry, staff), "值班长已确认，工单转待回访", True

        # 回访归档：客服录入回访结论后归档，并回写待回访清单状态。
        ok, reason = self._authorize_service(staff, entry)
        if not ok:
            return self._view(entry, staff), reason, False
        conclusion = str(values.get("回访结论") or "").strip()
        if not conclusion:
            return self._view(entry, staff), "回访结论不能为空", False
        entry["回访结论"] = conclusion
        entry["回访人"] = staff["姓名"]
        entry["回访时间"] = _now()
        entry["回访状态"] = "已回访"
        entry["status"] = target
        entry["pending"] = False
        self._log(entry, target, "回访归档", staff["姓名"], f"回访结论已回写客服工作台：{conclusion}")
        return self._view(entry, staff), "回访结论已回写待回访清单，工单归档", True

    # ---- 授权校验：越权当场驳回并说明缺哪项授权 ----
    def _authorize_claim(
        self, staff: dict[str, Any] | None, entry: dict[str, Any]
    ) -> tuple[bool, str]:
        crew = entry.get("责任班组")
        if staff is None:
            return False, f"认领被驳回：未识别值班身份，缺少「{crew} 值班人员」授权"
        if staff["班组"] != crew:
            return False, (
                f"认领被驳回：{staff['姓名']} 属{staff['班组']}，本工单责任班组为{crew}，"
                f"跨班组只读不可改，缺少「{crew} 值班人员」授权"
            )
        if "值班人员" not in staff["角色"]:
            return False, (
                f"认领被驳回：{staff['姓名']} 是{crew}{ '、'.join(staff['角色']) }，"
                f"缺少「{crew} 值班人员」授权"
            )
        return True, ""

    def _authorize_handler(
        self, staff: dict[str, Any] | None, entry: dict[str, Any]
    ) -> tuple[bool, str]:
        crew = entry.get("责任班组")
        if staff is None:
            return False, f"处置被驳回：未识别值班身份，缺少「{crew} 值班人员」授权"
        if staff["班组"] != crew or "值班人员" not in staff["角色"]:
            return False, (
                f"处置被驳回：跨班组或角色不符，{staff['姓名']} 缺少「{crew} 值班人员」授权，只读不可改"
            )
        if entry.get("认领人") and entry["认领人"] != staff["姓名"]:
            return False, (
                f"处置被驳回：本工单已由 {entry['认领人']} 认领，须由认领人填写处置结论"
            )
        return True, ""

    def _authorize_leader(
        self, staff: dict[str, Any] | None, entry: dict[str, Any]
    ) -> tuple[bool, str]:
        crew = entry.get("责任班组")
        if staff is None:
            return False, f"确认被驳回：未识别值班身份，缺少「{crew} 值班长」授权"
        if staff["班组"] != crew:
            return False, (
                f"确认被驳回：{staff['姓名']} 属{staff['班组']}，缺少「{crew} 值班长」授权"
            )
        if "值班长" not in staff["角色"]:
            return False, (
                f"确认被驳回：{staff['姓名']} 缺少「{crew} 值班长」授权，处置中工单未经值班长确认不得流转归档"
            )
        return True, ""

    def _authorize_service(
        self, staff: dict[str, Any] | None, entry: dict[str, Any]
    ) -> tuple[bool, str]:
        if staff is None:
            return False, "回访被驳回：未识别值班身份，缺少「客服」回访授权"
        if "客服" not in staff["角色"]:
            return False, f"回访被驳回：{staff['姓名']} 缺少「客服」回访授权"
        return True, ""

    # ---- 回访：两个入口读同一份主档 ----
    def callback_list(
        self, *, status: str | None = "待回访", keyword: str | None = None
    ) -> list[dict[str, Any]]:
        """客服工作台待回访清单：直接读投诉主档，归档后状态即变为已回访。"""
        rows = store.rows(MODULE)
        rows = [row for row in rows if row.get("status") in ("待回访", "已归档")]
        if status:
            if status == "待回访":
                rows = [row for row in rows if row.get("status") == "待回访"]
            elif status == "已回访":
                rows = [row for row in rows if row.get("回访状态") == "已回访"]
        if keyword:
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("工单编号", "")) or key in str(row.get("来电号码", ""))
            ]
        rows.sort(key=lambda row: (str(row.get("确认时间") or ""), int(row.get("id", 0))))
        return [self._callback_view(row) for row in rows]

    def track(self, keyword: str) -> dict[str, Any] | None:
        """另一处查询入口：按工单号/号码取回访状态，与客服工作台同源同值。"""
        key = keyword.strip()
        for row in store.rows(MODULE):
            if key in str(row.get("工单编号", "")) or key in str(row.get("来电号码", "")):
                view = self._callback_view(row)
                view["数据来源"] = "投诉工单主档"
                return view
        return None

    def _callback_view(self, row: dict[str, Any]) -> dict[str, Any]:
        # 只回写清单需要的字段，底层仍是同一条工单记录。
        return {
            "id": row.get("id"),
            "工单编号": row.get("工单编号"),
            "来电号码": row.get("来电号码"),
            "投诉类型": row.get("投诉类型"),
            "责任班组": row.get("责任班组"),
            "当前环节": row.get("status"),
            "回访状态": row.get("回访状态"),
            "回访结论": row.get("回访结论"),
            "回访人": row.get("回访人"),
            "回访时间": row.get("回访时间"),
        }

    # ---- 存量归属补录（不回填历史结论） ----
    def backfill_legacies(self) -> dict[str, Any]:
        """按受理顺序给缺责任班组的存量工单补归属；历史处置/回访结论原样保留。"""
        rows = sorted(store.rows(MODULE), key=lambda row: (str(row.get("受理时间") or ""), int(row.get("id", 0))))
        backfilled = 0
        preserved = 0
        for row in rows:
            if not row.get("是否存量"):
                continue
            if row.get("责任班组"):
                preserved += 1
                continue
            if row.get("归属补录"):
                continue
            crew = TYPE_CREW.get(str(row.get("投诉类型")))
            if not crew:
                continue
            row["责任班组"] = crew
            row["归属补录"] = True
            backfilled += 1
            self._log(
                row,
                str(row.get("status")),
                "存量归属补录",
                "系统",
                f"按新口径补派责任班组 {crew}；历史处置/回访结论保持原样不回填",
                at=BACKFILL_TIME,
            )
        return {"backfilled": backfilled, "preserved": preserved}

    def backfill_status(self) -> dict[str, Any]:
        rows = store.rows(MODULE)
        legacy = [row for row in rows if row.get("是否存量")]
        return {
            "legacy_total": len(legacy),
            "missing_crew": sum(1 for row in legacy if not row.get("责任班组")),
            "backfilled": sum(1 for row in legacy if row.get("归属补录")),
        }

    # ---- 视图组装：权限判断只在出参上标注，不落库、不改主档 ----
    def _view(self, row: dict[str, Any], staff: dict[str, Any] | None) -> dict[str, Any]:
        view = dict(row)
        writable, reason, actions = self._permissions(row, staff)
        view["可写"] = writable
        view["权限说明"] = reason
        view["可执行动作"] = actions
        return view

    def _permissions(
        self, row: dict[str, Any], staff: dict[str, Any] | None
    ) -> tuple[bool, str, list[str]]:
        stage = str(row.get("status"))
        crew = row.get("责任班组")
        if staff is None:
            return False, "未识别值班身份：当前只读", []

        same_crew = staff["班组"] == crew
        is_handler = same_crew and "值班人员" in staff["角色"]
        is_leader = same_crew and "值班长" in staff["角色"]
        is_service = "客服" in staff["角色"]

        actions: list[str] = []
        if stage == "待处置" and is_handler:
            actions = ["认领"]
        elif stage == "处置中":
            if is_handler and (not row.get("认领人") or row.get("认领人") == staff["姓名"]):
                actions.append("填写处置结论")
            if is_leader:
                actions.append("值班长确认")
        elif stage == "待回访" and is_service:
            actions = ["回访归档"]

        if actions:
            return True, "", actions
        if stage == "已归档":
            return False, "工单已归档，只读", []
        if is_service:
            return False, "客服环节仅可受理与回访，处置环节只读", []
        if staff["班组"] != crew:
            return False, f"跨班组只读：你属{staff['班组']}，本单责任班组为{crew}，无处置授权", []
        if not same_crew:
            return False, f"缺少「{crew}」相关授权，只读", []
        return False, f"当前身份在{crew}无可执行环节（需值班人员或值班长授权）", []

    def _log(
        self,
        entry: dict[str, Any],
        stage: str,
        action: str,
        actor: str,
        note: str = "",
        *,
        at: str | None = None,
    ) -> None:
        entry.setdefault("操作流水", []).append(
            {"时间": at or _now(), "环节": stage, "动作": action, "操作人": actor, "说明": note}
        )
