"""投诉工单业务规则：状态流转、重复投诉并单、班组授权与回访回写都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "complaint"
CALLBACK_MODULE = "callback"

REQUIRED_FIELDS = ["客户号码", "投诉类型", "投诉内容"]
COMPLAINT_TYPES = ["断站", "掉话", "资费"]
STATUS_ORDER = ["待处置", "处置中", "待回访", "已归档"]
ACTIONS = ["认领工单", "提交处置", "回访归档"]

# 投诉类型 → 责任班组 的派单口径；新单按它派，存量工单补归属也用同一口径
DISPATCH_RULES = {"断站": "网络运维一班", "掉话": "网络运维二班", "资费": "客服支撑班"}
DEFAULT_TEAM = "网络运维一班"

# 班组值班名册：leader 是值班长，members 是可认领处置的值班人员
TEAM_ROSTER = {
    "网络运维一班": {"leader": "王班长", "members": ["李工", "赵工"]},
    "网络运维二班": {"leader": "刘班长", "members": ["陈工", "周工"]},
    "客服支撑班": {"leader": "孙班长", "members": ["吴工", "郑工"]},
}
TEAMS = list(TEAM_ROSTER)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _next_ticket_no(rows: list[dict[str, Any]]) -> str:
    seq = 0
    for row in rows:
        no = str(row.get("工单编号") or "")
        if no.startswith("COMP-"):
            try:
                seq = max(seq, int(no.split("-", 1)[1]))
            except (ValueError, IndexError):
                continue
    return f"COMP-{seq + 1:04d}"


class ComplaintService:
    def __init__(self) -> None:
        # 存量工单迁移：服务起来时按受理顺序补上缺失的责任班组，历史处置结论不动
        self.backfill_missing_teams()

    # ----- 查询 -----
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        team: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("工单编号", "")) or keyword in str(row.get("客户号码", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if team:
            rows = [row for row in rows if row.get("责任班组") == team]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> dict[str, Any]:
        rows = store.rows(MODULE)
        counts = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        waiting = sum(1 for item in store.rows(CALLBACK_MODULE) if item.get("回访状态") == "待回访")
        cards = [{"label": f"{status}工单", "value": counts[status]} for status in STATUS_ORDER]
        cards.append({"label": "待回访任务", "value": waiting})
        return {"cards": cards}

    # ----- 受理与并单 -----
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        phone = str(values["客户号码"]).strip()
        complaint_type = str(values["投诉类型"]).strip()
        if complaint_type not in COMPLAINT_TYPES:
            return None, [], f"投诉类型只支持：{'、'.join(COMPLAINT_TYPES)}"
        accept_time = str(values.get("受理时间") or "").strip() or _now()
        accept_day = accept_time[:10]
        acceptor = str(values.get("受理人") or "").strip()
        content = str(values["投诉内容"]).strip()

        rows = store.rows(MODULE)
        # 同一号码当天只认第一次投诉，后续来电并到首单追加记录，不另开新单
        for row in rows:
            if str(row.get("客户号码")) == phone and str(row.get("受理时间", ""))[:10] == accept_day:
                row.setdefault("跟进记录", []).append({"时间": accept_time, "内容": content, "记录人": acceptor})
                row["追加次数"] = int(row.get("追加次数", 0)) + 1
                return row, [], f"该号码今日已受理工单 {row['工单编号']}，本次来电已并入追加记录，不另开新单"

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "工单编号": _next_ticket_no(rows),
            "客户号码": phone,
            "投诉类型": complaint_type,
            "投诉内容": content,
            "受理时间": accept_time,
            "受理人": acceptor,
            "责任班组": DISPATCH_RULES.get(complaint_type, DEFAULT_TEAM),
            "处置人": "",
            "处置结论": "",
            "值班长": "",
            "回访结论": "",
            "跟进记录": [],
            "追加次数": 0,
            "status": STATUS_ORDER[0],
            "工单状态": STATUS_ORDER[0],
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry, [], f"投诉工单 {entry['工单编号']} 已受理，派至{entry['责任班组']}"

    # ----- 状态流转 -----
    def run_action(self, entry_id: int, action: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"投诉工单 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于投诉工单可执行范围"
        current = str(entry.get("status") or "")
        if current == STATUS_ORDER[-1]:
            return None, "工单已归档，流程已闭环，不允许再回退或改单"
        try:
            if action == "认领工单":
                return self._claim(entry, values)
            if action == "提交处置":
                return self._submit_disposal(entry, values)
            return self._archive(entry, values)
        except ValueError as exc:
            return None, str(exc)

    def _claim(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        current = str(entry.get("status") or "")
        if current != "待处置":
            return None, f"工单当前为「{current}」，已走过待处置环节，不允许退回重新认领"
        denial = self._check_team_member(entry, values, verb="认领")
        if denial:
            return None, denial
        self._advance(entry, "处置中")
        entry["处置人"] = str(values.get("操作人") or "").strip()
        return entry, f"工单 {entry['工单编号']} 已由{entry['责任班组']}{entry['处置人']}认领，转入处置中"

    def _submit_disposal(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        current = str(entry.get("status") or "")
        if current != "处置中":
            return None, f"工单当前为「{current}」，不能提交处置结论"
        denial = self._check_team_member(entry, values, verb="处置")
        if denial:
            return None, denial
        conclusion = str(values.get("处置结论") or "").strip()
        if not conclusion:
            return None, "提交处置必须填写处置结论"
        team = str(entry.get("责任班组") or "")
        expected_leader = TEAM_ROSTER[team]["leader"]
        leader = str(values.get("值班长") or "").strip()
        if leader != expected_leader:
            return None, f"处置中工单须值班长确认后才能转待回访：缺少「{team}」值班长{expected_leader}的确认"
        entry["处置结论"] = conclusion
        entry["值班长"] = leader
        self._advance(entry, "待回访")
        self._open_callback(entry)
        return entry, f"工单 {entry['工单编号']} 处置结论已经值班长确认，转入待回访"

    def _archive(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        current = str(entry.get("status") or "")
        if current == "处置中":
            return None, "处置中工单未经值班长确认并提交处置，不许直接归档"
        if current != "待回访":
            return None, f"工单当前为「{current}」，不能执行回访归档"
        conclusion = str(values.get("回访结论") or "").strip()
        if not conclusion:
            return None, "归档前必须填写回访结论"
        entry["回访结论"] = conclusion
        self._advance(entry, "已归档")
        self._close_callback(entry, conclusion)
        return entry, f"工单 {entry['工单编号']} 回访完成已归档，回访结论已回写客服工作台"

    def _advance(self, entry: dict[str, Any], target: str) -> None:
        """只能顺着待处置→处置中→待回访→已归档走，回退或跳级在这里被最终拦下。"""
        current = str(entry.get("status") or "")
        if current not in STATUS_ORDER or target not in STATUS_ORDER:
            raise ValueError("工单状态不在允许的状态序列里")
        if STATUS_ORDER.index(target) != STATUS_ORDER.index(current) + 1:
            raise ValueError(f"工单只能顺着{'→'.join(STATUS_ORDER)}流转，不允许退回或跳级")
        entry["status"] = target
        entry["工单状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]

    def _check_team_member(self, entry: dict[str, Any], values: dict[str, Any], *, verb: str) -> str | None:
        """认领与处置只放行本班组值班人员；越权时说明缺哪项授权。"""
        team = str(entry.get("责任班组") or "").strip()
        operator = str(values.get("操作人") or "").strip()
        team_name = str(values.get("所属班组") or "").strip()
        if not operator or not team_name:
            return f"{verb}需提供操作人与所属班组，才能核验处置授权"
        roster = TEAM_ROSTER.get(team)
        if roster is None:
            return f"责任班组「{team}」不在值班名册里，请先维护班组授权"
        if team_name != team:
            return f"越权{verb}已驳回：工单归属「{team}」，{team_name}缺少该班组的处置授权"
        if operator != roster["leader"] and operator not in roster["members"]:
            return f"越权{verb}已驳回：{operator}不在「{team}」值班名册，缺少本班组值班授权"
        return None

    # ----- 回访清单：客服工作台与单条查询读同一份数据 -----
    def list_callbacks(self, *, status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(CALLBACK_MODULE)
        if status:
            rows = [row for row in rows if row.get("回访状态") == status]
        return rows

    def get_callback_for_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        ticket_no = str(entry.get("工单编号") or "")
        for row in store.rows(CALLBACK_MODULE):
            if row.get("工单编号") == ticket_no:
                return row
        return None

    def _open_callback(self, entry: dict[str, Any]) -> None:
        rows = store.rows(CALLBACK_MODULE)
        if any(row.get("工单编号") == entry["工单编号"] for row in rows):
            return
        rows.append({
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "工单编号": entry["工单编号"],
            "客户号码": entry["客户号码"],
            "责任班组": entry.get("责任班组", ""),
            "回访状态": "待回访",
            "回访结论": "",
            "回访时间": "",
            "生成时间": _now(),
        })

    def _close_callback(self, entry: dict[str, Any], conclusion: str) -> None:
        rows = store.rows(CALLBACK_MODULE)
        record = next((row for row in rows if row.get("工单编号") == entry["工单编号"]), None)
        if record is None:
            self._open_callback(entry)
            record = rows[-1]
        record["回访状态"] = "已回访"
        record["回访结论"] = conclusion
        record["回访时间"] = _now()
        record["责任班组"] = entry.get("责任班组", record.get("责任班组", ""))

    # ----- 存量迁移 -----
    def backfill_missing_teams(self) -> list[dict[str, Any]]:
        """按受理顺序给没有责任班组的存量工单补归属；历史处置结论保留，不按新口径回填。"""
        rows = [row for row in store.rows(MODULE) if not str(row.get("责任班组") or "").strip()]
        rows.sort(key=lambda row: (str(row.get("受理时间") or ""), int(row.get("id", 0))))
        for row in rows:
            row["责任班组"] = DISPATCH_RULES.get(str(row.get("投诉类型") or "").strip(), DEFAULT_TEAM)
        return rows
