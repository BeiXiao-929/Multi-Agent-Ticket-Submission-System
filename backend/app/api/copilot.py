"""Ticket drafting and skill discovery routes."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from ..assistant.workflow import analyze_ticket
from ..core.llm import is_meaningful
from ..skills.loader import discover_skills

router = APIRouter()


class AnalyzeRequest(BaseModel):
    title: str = Field("", max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    submitter: str = Field("", max_length=100)
    priority: str = Field("", pattern="^(low|normal|high|)?$")

    @field_validator("description")
    @classmethod
    def description_must_be_meaningful(cls, value: str) -> str:
        if not is_meaningful(value):
            raise ValueError("请提供可识别的工单描述")
        return value.strip()


@router.post("/copilot/analyze")
def analyze(body: AnalyzeRequest) -> dict:
    """Create a reviewable ticket draft without persisting it."""
    return analyze_ticket(body.model_dump())


@router.get("/copilot/skills")
def list_skills() -> dict:
    skills = [skill.as_dict() for skill in discover_skills()]
    return {
        "count": len(skills),
        "skills": skills,
        "to_tickets_upstream": "unavailable; local compatible implementation active",
    }
