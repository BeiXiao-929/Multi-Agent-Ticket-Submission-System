from __future__ import annotations

import json
import logging
import re

from ..config import settings

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Department vocabulary
# ---------------------------------------------------------------------------
DEPTS = ["IT", "HR", "PROCUREMENT", "FINANCE", "OTHER"]

#: Per-department required-field rules. Each rule is a list of field dicts:
#:   {"key": "...", "kw": [trigger keywords], "need": [accepting keywords]}
_INFO_RULES: dict[str, list[dict]] = {
    "IT": [
        {
            "key": "asset_detail",
            "kw": ["电脑", "笔记本", "打不开", "不开机", "蓝屏", "故障", "损坏", "打印机", "设备"],
            "need": ["资产编号", "asset"],
        },
    ],
    "PROCUREMENT": [
        {"key": "model", "kw": ["服务器", "采购", "购买", "订购", "设备"], "need": ["型号", "model", "规格"]},
        {"key": "budget", "kw": ["服务器", "采购", "购买", "订购", "设备", "预算"], "need": ["预算", "b", "万元", "元"]},
    ],
    "FINANCE": [
        {"key": "amount", "kw": ["报销", "打车", "费用", "付款"], "need": ["元", "块", "¥", "usd", "budget"]},
    ],
    "HR": [],  # HR requests are answered from local demo data.
}

_DEFAULT_CLARIFICATIONS: dict[str, str] = {
    "IT": "请补充您的设备资产编号（如 DESKTOP-xxxx / LAPTOP-xxxx）以及具体故障现象（打不开机 / 蓝屏 / 无信号等），以便 IT 尽快派单。",
    "PROCUREMENT": "请补充采购物品的型号/规格与预算金额（例如：Dell R750，预算 8 万元），以便走对应审批流。",
    "FINANCE": "请补充报销金额与费用类型（例如：打车 50 元 / 差旅 1200 元），财务才能进入复核队列。",
    "HR": "请补充具体的 HR 诉求（请假 / 证明 / 政策咨询等）。",
    "OTHER": "请重新描述您的具体需求。",
}


# ---------------------------------------------------------------------------
# Input sanity guards
# ---------------------------------------------------------------------------
def is_meaningful(text: str) -> bool:
    """Return False when the text is empty, pure symbols, or effectively
    incoherent (e.g. '????？' or 'asdasdasd')."""
    s = (text or "").strip()
    if not s:
        return False
    # Remove everything that is NOT a CJK char, letter, digit, or whitespace
    content = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9\s]", "", s)
    tokens = [t for t in content.split() if t]
    if len(content) < 4:
        return False
    # Very short, all-lowercase-ascii runs with no CJK are treated as junk
    if not re.search(r"[\u4e00-\u9fff]", s):
        letters = re.findall(r"[A-Za-z]", s)
        if len(letters) < 3:
            return False
    # Repeated-char spam like 'aaaaa...'
    if tokens:
        longest_repeats = max(len(re.findall(r"(.)\1{4,}", t)) for t in tokens) if tokens else 0
        if longest_repeats >= 3:
            return False
    return True


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
_CLASSIFY_SYSTEM = """你是企业内部多智能体工单系统的编排 Agent（orchestrator）。
任务：从用户输入中识别所有独立意图（multi-intent），并按部门路由。

- 每个意图必须归属到 IT / HR / PROCUREMENT / FINANCE / OTHER 之一。
- 用户一句话可能同时涉及多个部门：例如"电脑没发 + 公积金 + 打车报销"
  就是 3 个意图。请识别出【所有】独立意图，不要只挑最主要的。
- 输出必须是严格 JSON（不要任何多余文字、markdown 或注释）：

{
  "primary_dept": "IT",
  "confidence": 0.92,
  "multi_intent": true,
  "sub_intents": [
    {"dept": "IT", "confidence": 0.9, "span": "电脑没发"},
    {"dept": "HR", "confidence": 0.8, "span": "公积金多少"}
  ]
}

- sub_intents 中每个 dept 只能出现一次；span 是原文片段（尽量不超过 20 字）。
- 如果只有单一意图，sub_intents 里仍然列出该意图一条。
"""

_DEPT_KEYWORDS: dict[str, list[str]] = {
    "IT": ["电脑", "笔记本", "打印机", "网络", "WiFi", "vpn", "权限", "账号", "密码", "软件", "安装", "设备", "故障", "打不开", "蓝屏", "ip", "路由", "系统"],
    "HR": ["公积金", "社保", "年假", "请假", "考勤", "打卡", "证明", "在职", "薪资", "工资", "入职", "离职", "政策", "调休"],
    "PROCUREMENT": ["采购", "供应商", "买东西", "买一台", "服务器", "办公", "办公用品", "采购发票", "订购", "设备采购"],
    "FINANCE": ["报销", "发票", "财务", "预算", "付款", "账单", "打款", "费用"],
}


def _keyword_classify(text: str) -> dict:
    """Rule-based multi-intent classifier mirroring the LLM's JSON shape."""
    sub_intents: list[dict] = []
    lowered = text.lower()
    for dept, kws in _DEPT_KEYWORDS.items():
        hits = [kw for kw in kws if kw in lowered]
        if hits:
            sub_intents.append({
                "dept": dept,
                "confidence": min(0.95, 0.5 + 0.15 * len(hits)),
                "span": hits[0],
                "source": "keyword",
            })
    if not sub_intents:
        sub_intents = [{"dept": "OTHER", "confidence": 0.4, "span": text[:20], "source": "fallback"}]
    primary = max(sub_intents, key=lambda x: x["confidence"])
    multi = len([s for s in sub_intents if s["dept"] != primary["dept"]]) >= 1 and len(sub_intents) >= 2
    return {
        "primary_dept": primary["dept"],
        "confidence": primary["confidence"],
        "multi_intent": multi,
        "sub_intents": sub_intents,
        "source": "keyword",
    }


def _parse_llm_response(raw: str) -> dict | None:
    """Extract the JSON object from the LLM reply. Tolerates wrapping
    markdown fences and leading prose."""
    raw = raw.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "primary_dept" not in data:
        return None
    data.setdefault("sub_intents", [])
    # Sanitise: keep only known depts, dedupe
    seen: set[str] = set()
    cleaned = []
    for it in data["sub_intents"]:
        dept = str(it.get("dept", "")).upper()
        if dept not in DEPTS or dept in seen:
            continue
        seen.add(dept)
        cleaned.append({
            "dept": dept,
            "confidence": float(it.get("confidence", 0.5)),
            "span": str(it.get("span", ""))[:40],
        })
    if not cleaned:
        cleaned = [{"dept": "OTHER", "confidence": 0.4, "span": ""}]
    data["sub_intents"] = cleaned
    if data["primary_dept"] not in DEPTS:
        data["primary_dept"] = cleaned[0]["dept"]
    data.setdefault("confidence", cleaned[0]["confidence"])
    data["multi_intent"] = data.get("multi_intent") or len(cleaned) > 1
    data["source"] = "llm"
    return data


def classify_with_fallback(text: str) -> dict:
    """Run LLM multi-intent classification with a hard keyword fallback.

    Garbage / pure-symbol input is routed to OTHER with a gentle hint,
    without raising.
    """
    text = (text or "").strip()
    if not is_meaningful(text):
        logger.info("classify: meaningless input routed to OTHER")
        return {
            "primary_dept": "OTHER",
            "confidence": 0.2,
            "multi_intent": False,
            "sub_intents": [
                {"dept": "OTHER", "confidence": 0.2, "span": text[:20], "source": "guard"}
            ],
            "hint": "系统未能理解您的具体需求，请重新描述。",
            "source": "guard",
        }

    if settings.llm_enabled and settings.llm_api_key:
        try:
            raw = _call_llm(_CLASSIFY_SYSTEM, text)
            parsed = _parse_llm_response(raw)
            if parsed:
                return parsed
            logger.warning("LLM classification returned unparsable JSON; using keyword fallback")
        except Exception as exc:  # pragma: no cover - network paths
            logger.warning("LLM classification failed (%s); using keyword fallback", exc)

    return _keyword_classify(text)


# ---------------------------------------------------------------------------
# Info-completeness check
# ---------------------------------------------------------------------------
def check_info_complete(dept: str, text: str, result_meta: dict | None = None) -> dict:
    """Return {"complete": bool, "missing": [...], "questions": [...]}
    based on the department's required-field rules."""
    result_meta = result_meta or {}
    meta_str = json.dumps(result_meta, ensure_ascii=False).lower() if result_meta else ""
    lowered = f"{text} {meta_str}".lower()
    missing: list[str] = []
    questions: list[str] = []
    for rule in _INFO_RULES.get(dept, []):
        triggered = any(kw in lowered for kw in rule["kw"])
        if not triggered:
            continue
        if not any(need in lowered for need in rule["need"]):
            missing.append(rule["key"])
            questions.append(_DEFAULT_CLARIFICATIONS.get(dept, ""))
    return {"complete": not missing, "missing": missing, "questions": list(dict.fromkeys(questions))}


def build_clarification(dept: str, text: str, missing: list[str]) -> str:
    """Ask the LLM for a natural follow-up question; fall back to a
    department template."""
    template = _DEFAULT_CLARIFICATIONS.get(dept, "请补充相关信息。")
    if not settings.llm_enabled or not settings.llm_api_key:
        return template
    prompt = (
        f"用户工单（{dept} 部门）：{text}\n"
        f"系统发现缺失信息项：{', '.join(missing)}\n"
        f"请生成一条不超过 60 字的礼貌追问，要求用户提供上述缺失信息。"
        "直接输出追问语句，不要加任何解释。"
    )
    try:
        reply = _call_llm("你是企业工单系统的客服 Agent，请只输出一句追问。", prompt)
        reply = (reply or "").strip().strip('"')
        return reply or template
    except Exception as exc:  # pragma: no cover
        logger.warning("clarification LLM call failed (%s); using template", exc)
        return template


# ---------------------------------------------------------------------------
# Generic LLM helper
# ---------------------------------------------------------------------------
def _call_llm(system: str, user: str) -> str:
    """Single-shot chat call against the configured provider (agnes)."""
    import httpx  # local import to keep module import-time light

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.llm_api_key}",
    }
    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    last_err: Exception | None = None
    for attempt in range(1, settings.llm_max_retries + 1):
        try:
            with httpx.Client(timeout=settings.llm_timeout_s) as client:
                r = client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            last_err = exc
            logger.debug("LLM call attempt %d failed: %s", attempt, exc)
    raise RuntimeError(f"LLM unavailable after {settings.llm_max_retries} attempts: {last_err}")
