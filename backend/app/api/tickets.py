"""Ticket submission + query routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from ..agents.registry import get_registry
from ..core.llm import is_meaningful
from ..state.store import TicketStore

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class TicketSubmit(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=2000)
    submitter: str | None = None
    priority: str = Field("normal", pattern="^(low|normal|high)$")
    result_meta: dict = Field(default_factory=dict, description="Optional agent-specific metadata such as device_id, user_id, amount, dept")

    @field_validator("content")
    @classmethod
    def _content_must_be_meaningful(cls, v: str) -> str:
        """Reject empty, pure-symbol, or clearly unusable input."""
        if not is_meaningful(v):
            raise ValueError("描述内容为纯符号或无法识别，请提供有效文本")
        return v

    @field_validator("title")
    @classmethod
    def _title_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v


class SubTicketOut(BaseModel):
    id: str
    parent_id: str
    dept: str
    intent_label: str | None
    status: str
    confidence: float | None
    result: dict | None


class TicketOut(BaseModel):
    id: str
    title: str
    description: str
    submitter: str
    priority: str
    status: str
    primary_dept: str | None
    confidence: float | None
    multi_intent: bool
    created_at: str
    updated_at: str
    meta: dict


class TicketUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1, max_length=2000)
    submitter: str | None = None
    priority: str | None = Field(None, pattern="^(low|normal|high)$")

    @field_validator("title")
    @classmethod
    def _update_title_strip(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("标题不能为 null")
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v

    @field_validator("description")
    @classmethod
    def _update_description_must_be_meaningful(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("描述不能为 null")
        if not is_meaningful(v):
            raise ValueError("描述内容为纯符号或无法识别，请提供有效文本")
        return v

    @field_validator("submitter")
    @classmethod
    def _update_submitter_strip(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("提交人不能为 null")
        v = v.strip()
        if not v:
            raise ValueError("提交人不能为空")
        return v

    @field_validator("priority")
    @classmethod
    def _update_priority_not_null(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("优先级不能为 null")
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self) -> TicketUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的字段")
        return self


class SubmitResponse(BaseModel):
    ticket_id: str
    primary_dept: str
    confidence: float
    multi_intent: bool
    sub_intents: list[dict]
    sub_ticket_ids: list[str]
    hint: str | None = None


class AppendInfoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/tickets/submit", response_model=SubmitResponse)
def submit_ticket(body: TicketSubmit) -> SubmitResponse:
    """Accept a raw ticket, run classification + multi-intent splitting, and
    dispatch the sub-tickets to the right agents."""
    if body.submitter is None:
        body.submitter = "anonymous"
    # Inject any agent-specific fields (device_id, user_id, amount, ...)
    orch = get_registry().orchestrator
    payload = body.model_dump()
    payload["result_meta"] = body.result_meta or {}
    return SubmitResponse(**orch.handle_submission(payload))


@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(limit: int = 50, offset: int = 0):
    """Return the most recent tickets (newest first)."""
    return TicketStore.list_tickets(limit=limit, offset=offset)


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str) -> TicketOut:
    ticket = TicketStore.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return TicketOut(**ticket)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: str, body: TicketUpdate) -> TicketOut:
    """Update editable ticket fields. Workflow state remains agent-managed."""
    patch = body.model_dump(exclude_unset=True)
    if not TicketStore.update_ticket(ticket_id, patch):
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket = TicketStore.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return TicketOut(**ticket)


@router.delete("/tickets/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: str) -> Response:
    """Delete a ticket together with its sub-tickets and snapshots."""
    if not TicketStore.delete_ticket(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return Response(status_code=204)


@router.get("/tickets/{ticket_id}/sub-tickets", response_model=list[SubTicketOut])
def get_sub_tickets(ticket_id: str) -> list[SubTicketOut]:
    parent = TicketStore.get_ticket(ticket_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent ticket not found")
    return [SubTicketOut(**s) for s in TicketStore.list_sub_tickets(ticket_id)]


@router.get("/tickets/{ticket_id}/result")
def get_aggregated_result(ticket_id: str) -> dict:
    """Aggregate all sub-ticket results into a single unified reply."""
    parent = TicketStore.get_ticket(ticket_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return get_registry().orchestrator.aggregate_results(ticket_id)


@router.post("/tickets/{ticket_id}/sub-tickets/{sub_id}/append-info")
def append_info(ticket_id: str, sub_id: str, body: AppendInfoRequest) -> dict:
    """Accept user-supplied follow-up for a sub-ticket parked in
    ``waiting_info`` and re-dispatch it to its owning agent."""
    parent = TicketStore.get_ticket(ticket_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    sub = TicketStore.get_sub_ticket(sub_id)
    if sub is None or sub.get("parent_id") != ticket_id:
        raise HTTPException(status_code=404, detail="Sub-ticket not found")
    if sub.get("status") != "waiting_info":
        raise HTTPException(
            status_code=409,
            detail=f"Sub-ticket is in state '{sub.get('status')}', not waiting_info",
        )
    try:
        updated = get_registry().orchestrator.append_info(sub_id, body.text.strip())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"sub_ticket": updated, "parent_id": ticket_id}
