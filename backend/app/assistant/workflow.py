"""LangGraph ticket drafting workflow exposed through CopilotKit."""
from __future__ import annotations

import re
import uuid
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ..core.llm import classify_with_fallback
from ..skills.loader import discover_skills
from .retrieval import local_retriever


class TicketAssistantState(TypedDict, total=False):
    title: str
    description: str
    submitter: str
    priority: str
    draft: dict[str, Any]
    analysis: dict[str, Any]
    missing_fields: list[dict[str, str]]
    retrieval: dict[str, list[dict[str, Any]]]
    assistant_message: str
    skills: list[dict[str, Any]]


class CopilotState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    analysis: dict[str, Any]


_TYPE_RULES = {
    "incident": ("故障", "报错", "无法", "打不开", "蓝屏", "宕机", "异常", "失败"),
    "access": ("权限", "账号", "账户", "密码", "登录", "vpn", "开通"),
    "procurement": ("采购", "购买", "订购", "供应商", "预算", "服务器"),
    "reimbursement": ("报销", "发票", "费用", "付款", "账单"),
    "hr": ("入职", "离职", "请假", "年假", "公积金", "社保", "证明"),
    "question": ("怎么", "如何", "咨询", "是否", "政策"),
}

_TAG_RULES = {
    "urgent": ("紧急", "立刻", "马上", "尽快", "影响工作", "全员", "生产"),
    "security": ("钓鱼", "病毒", "勒索", "泄露", "安全", "异常登录"),
    "network": ("网络", "wifi", "vpn", "断网", "路由"),
    "device": ("电脑", "笔记本", "打印机", "显示器", "设备"),
    "budget": ("预算", "金额", "万元", "元", "费用"),
}

_DEPT_LABEL = {
    "IT": "信息技术",
    "HR": "人力资源",
    "PROCUREMENT": "采购",
    "FINANCE": "财务",
    "OTHER": "综合",
}


def _compact(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _infer_title(text: str, supplied: str) -> str:
    if supplied.strip():
        return _compact(supplied, 200)
    first = re.split(r"[。！？!?\n]", text, maxsplit=1)[0].strip()
    if len(first) < 4:
        first = text.strip()
    return _compact(first or "未命名工单", 60)


def _infer_priority(text: str, supplied: str) -> str:
    if supplied in {"low", "normal", "high"}:
        return supplied
    if any(keyword in text.lower() for keyword in ("紧急", "立刻", "马上", "尽快", "p0", "p1", "生产故障", "全员")):
        return "high"
    if any(keyword in text for keyword in ("不急", "低优先", "有空再处理")):
        return "low"
    return "normal"


def _infer_type(text: str) -> str:
    lowered = text.lower()
    for ticket_type, keywords in _TYPE_RULES.items():
        if any(keyword in lowered for keyword in keywords):
            return ticket_type
    return "request"


def _related_people(text: str) -> list[str]:
    people = re.findall(r"(?:给|找|联系|通知|负责人[:：]?|审批人[:：]?)\s*([\u4e00-\u9fff]{2,4})", text)
    ignored = {"我们", "你们", "他们", "一下", "处理", "审批", "部门"}
    return list(dict.fromkeys(person for person in people if person not in ignored))[:5]


def _deadline(text: str) -> str | None:
    patterns = (
        r"(?:今天|明天|后天|本周[一二三四五六日天]?|下周[一二三四五六日天]?)",
        r"\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?",
        r"\d{1,2}月\d{1,2}日",
        r"\d{1,2}月\d{1,2}号",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _tags(text: str, department: str, ticket_type: str) -> list[str]:
    lowered = text.lower()
    tags = [department, ticket_type]
    for tag, keywords in _TAG_RULES.items():
        if any(keyword in lowered for keyword in keywords):
            tags.append(tag)
    return list(dict.fromkeys(tags))


def _skill_metadata() -> list[dict[str, Any]]:
    interesting = {"to-tickets", "brainstorming", "systematic-debugging", "verification-before-completion"}
    return [skill.as_dict() for skill in discover_skills() if skill.name in interesting]


def _extract_node(state: TicketAssistantState) -> dict[str, Any]:
    title = state.get("title", "")
    description = state.get("description", "").strip()
    text = f"{title}\n{description}".strip()
    classification = classify_with_fallback(text)
    department = classification.get("primary_dept", "OTHER")
    ticket_type = _infer_type(text)
    draft = {
        "title": _infer_title(text, title),
        "description": _compact(description or text, 2000),
        "submitter": state.get("submitter", "").strip(),
        "priority": _infer_priority(text, state.get("priority", "")),
        "department": department,
        "department_label": _DEPT_LABEL.get(department, department),
        "type": ticket_type,
        "intents": [item.get("span") or item.get("dept") for item in classification.get("sub_intents", [])],
        "related_people": _related_people(text),
        "deadline": _deadline(text),
        "tags": _tags(text, department, ticket_type),
        "confirmation_required": True,
    }
    return {
        "draft": draft,
        "analysis": {
            "confidence": classification.get("confidence", 0.0),
            "multi_intent": classification.get("multi_intent", False),
            "classification_source": classification.get("source", "keyword"),
            "hint": classification.get("hint"),
        },
        "skills": _skill_metadata(),
    }


def _completeness_node(state: TicketAssistantState) -> dict[str, Any]:
    draft = state.get("draft", {})
    text = f"{draft.get('title', '')}\n{draft.get('description', '')}".lower()
    department = draft.get("department", "OTHER")
    missing: list[dict[str, str]] = []

    if not draft.get("submitter"):
        missing.append({
            "key": "submitter",
            "label": "提交人",
            "question": "请填写提交人，便于处理人联系。",
            "severity": "recommended",
        })

    if department == "IT":
        device_issue = any(keyword in text for keyword in ("电脑", "笔记本", "打印机", "设备", "蓝屏", "不开机"))
        has_asset = bool(re.search(r"(?:资产编号|asset|设备编号|[a-z]{2,6}[-_]?\d{3,})", text))
        if device_issue and not has_asset:
            missing.append({
                "key": "asset_id",
                "label": "设备编号",
                "question": "请补充设备编号或资产编号。",
                "severity": "required",
            })
        if any(keyword in text for keyword in ("故障", "打不开", "蓝屏", "断网")):
            missing.append({
                "key": "impact_scope",
                "label": "影响范围",
                "question": "这个问题影响您个人、单个部门还是多名同事？",
                "severity": "recommended",
            })
    elif department == "PROCUREMENT":
        if not any(keyword in text for keyword in ("型号", "规格", "配置", "model")):
            missing.append({
                "key": "model",
                "label": "型号或规格",
                "question": "请补充采购物品的型号、规格或配置。",
                "severity": "required",
            })
        if not re.search(r"(?:预算|金额|\d+(?:\.\d+)?\s*(?:元|万元|块))", text):
            missing.append({
                "key": "budget",
                "label": "预算金额",
                "question": "请补充预算金额和币种。",
                "severity": "required",
            })
    elif department == "FINANCE":
        if not re.search(r"\d+(?:\.\d+)?\s*(?:元|块|万元|usd|cny|rmb)", text):
            missing.append({
                "key": "amount",
                "label": "金额",
                "question": "请补充报销或付款金额及币种。",
                "severity": "required",
            })
    elif department == "HR":
        if not any(keyword in text for keyword in ("入职", "离职", "请假", "公积金", "社保", "证明", "薪资", "考勤", "政策")):
            missing.append({
                "key": "hr_request_type",
                "label": "HR 事项类型",
                "question": "请说明这是哪类 HR 事项。",
                "severity": "required",
            })

    if draft.get("priority") == "high" and not draft.get("deadline"):
        missing.append({
            "key": "deadline",
            "label": "期望完成时间",
            "question": "这是高优先级工单，请补充期望完成时间。",
            "severity": "recommended",
        })

    deduped: dict[str, dict[str, str]] = {}
    for item in missing:
        deduped.setdefault(item["key"], item)
    return {"missing_fields": list(deduped.values())}


def _retrieve_node(state: TicketAssistantState) -> dict[str, Any]:
    draft = state.get("draft", {})
    query = " ".join(
        value for value in (
            draft.get("title"),
            draft.get("description"),
            " ".join(draft.get("tags", [])),
        ) if value
    )
    _, context = local_retriever.search_bundle(query, top_k=8)
    return {"retrieval": context}


def _compose_node(state: TicketAssistantState) -> dict[str, Any]:
    draft = state.get("draft", {})
    missing = state.get("missing_fields", [])
    knowledge = state.get("retrieval", {}).get("knowledge", [])
    similar = state.get("retrieval", {}).get("similar_tickets", [])
    lines = [
        f"已整理为 {draft.get('department_label', draft.get('department', '综合'))}工单草稿。",
        f"建议优先级：{draft.get('priority', 'normal')}；类型：{draft.get('type', 'request')}。",
    ]
    if missing:
        lines.append("提交前建议补充：" + "；".join(item["question"] for item in missing[:4]))
    if knowledge:
        lines.append("参考知识：" + "；".join(item["title"] for item in knowledge[:2]))
    if similar:
        lines.append(f"找到 {len(similar)} 条相似历史工单。")
    lines.append("请在表单中复核后手动点击“提交工单”。")
    return {"assistant_message": "\n".join(lines)}


@lru_cache(maxsize=1)
def _analysis_graph():
    builder = StateGraph(TicketAssistantState)
    builder.add_node("extract", _extract_node)
    builder.add_node("check_completeness", _completeness_node)
    builder.add_node("retrieve_context", _retrieve_node)
    builder.add_node("compose", _compose_node)
    builder.add_edge(START, "extract")
    builder.add_edge("extract", "check_completeness")
    builder.add_edge("check_completeness", "retrieve_context")
    builder.add_edge("retrieve_context", "compose")
    builder.add_edge("compose", END)
    return builder.compile(checkpointer=InMemorySaver())


def analyze_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    result = _analysis_graph().invoke(
        {
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "submitter": payload.get("submitter", ""),
            "priority": payload.get("priority", ""),
        },
        config={"configurable": {"thread_id": f"analysis-{run_id}"}},
    )
    return {
        "run_id": run_id,
        "draft": result.get("draft", {}),
        "analysis": result.get("analysis", {}),
        "missing_fields": result.get("missing_fields", []),
        "knowledge": result.get("retrieval", {}).get("knowledge", []),
        "similar_tickets": result.get("retrieval", {}).get("similar_tickets", []),
        "assistant_message": result.get("assistant_message", ""),
        "skills": result.get("skills", []),
        "confirmation_required": True,
    }


def _copilot_node(state: CopilotState) -> dict[str, Any]:
    human_text = ""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            human_text = message.content if isinstance(message.content, str) else str(message.content)
            break
    if not human_text.strip():
        human_text = "请分析当前工单表单。"
    analysis = analyze_ticket({"title": "", "description": human_text, "priority": "normal"})
    draft = analysis["draft"]
    questions = [item["question"] for item in analysis["missing_fields"][:3]]
    content = analysis["assistant_message"]
    if questions:
        content += "\n待补充：" + " ".join(questions)
    return {
        "analysis": analysis,
        "messages": [
            AIMessage(
                content=content,
                tool_calls=[{
                    "name": "fillTicketForm",
                    "args": {
                        "title": draft.get("title", ""),
                        "description": draft.get("description", human_text),
                        "priority": draft.get("priority", "normal"),
                        "submitter": draft.get("submitter", ""),
                    },
                    "id": f"call_{uuid.uuid4().hex}",
                }],
            )
        ],
    }


@lru_cache(maxsize=1)
def build_copilot_graph():
    builder = StateGraph(CopilotState)
    builder.add_node("ticket_assistant", _copilot_node)
    builder.add_edge(START, "ticket_assistant")
    builder.add_edge("ticket_assistant", END)
    return builder.compile(checkpointer=InMemorySaver())
