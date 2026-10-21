---
name: to-tickets
description: Convert free-form conversation or incident notes into a structured, reviewable ticket draft.
version: 1.0.0-local
license: MIT
---

# Convert a conversation into tickets

Use this skill when a user describes one or more needs in natural language and the system must prepare ticket data for review.

## Rules

1. Preserve facts. Do not invent asset IDs, budgets, people, deadlines, or approval status.
2. Extract every independent intent. A sentence may contain IT, HR, procurement, and finance requests at the same time.
3. Produce a concise title, a self-contained description, a priority (`low`, `normal`, `high`), a ticket type, a target department, tags, related people, and a deadline when explicitly stated.
4. List missing mandatory fields as questions. Never silently replace a missing value with a guessed one.
5. Return only structured data. The webpage may apply the draft to its form, but a human must review it and click the existing submit button.

## Standard output

```json
{
  "title": "Short ticket title",
  "description": "Complete description based on user-provided facts",
  "priority": "normal",
  "type": "incident",
  "department": "IT",
  "intents": ["network access"],
  "related_people": [],
  "deadline": null,
  "tags": ["IT", "incident"],
  "missing_fields": [
    {"key": "asset_id", "label": "设备编号", "question": "请提供设备编号。"}
  ],
  "dependencies": [],
  "confirmation_required": true
}
```

## Priority guide

- `high`: outage, security, blocked work, explicit urgency, or a near deadline.
- `normal`: ordinary work requests and questions.
- `low`: cosmetic issues or requests explicitly marked as non-urgent.
