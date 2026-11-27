from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.api.deps import get_engagement_store, get_stream_store
from arp.schemas.engagement import (
    CorrespondenceType,
    InteractionType,
    IssueSeverity,
    IssueStatus,
    TriggerSource,
)
from arp.stewardship import case_study, drafting, monitoring
from arp.stewardship.client_report import build_pptx, client_report
from arp.stewardship.config_store import PolicyStore, StreamStore
from arp.stewardship.sample import load_sample
from arp.stewardship.style import check as style_check
from arp.stewardship.trigger_store import TriggerStore, trigger_id
from arp.stewardship.universe import HouseUniverseSetting
from arp.storage.postgres_engagement_store import PostgresEngagementStore as EngagementStore

router = APIRouter(prefix="/api/stewardship", tags=["stewardship"])


# --- Versioned house configs (priority_weights, phrase_blocklist, monitoring_rules) ---


def _store(streams: StreamStore, policy_id: str) -> PolicyStore:
    store = PolicyStore(streams.root)
    try:
        store.versions(policy_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown policy") from exc
    return store


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, streams: StreamStore = Depends(get_stream_store)) -> dict:
    store = _store(streams, policy_id)
    active = store.active_version(policy_id)
    return {
        "policy_id": policy_id,
        "active_version": active,
        "active": store.content(policy_id, active),
        "versions": store.versions(policy_id),
        "activations": store.activations(policy_id),
    }


@router.get("/policies/{policy_id}/versions/{version}")
def get_policy_version(policy_id: str, version: int, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        return _store(streams, policy_id).content(policy_id, version)
    except KeyError as exc:
        raise HTTPException(404, "Unknown version") from exc


class SavePolicyRequest(BaseModel):
    content: dict
    note: str = ""


@router.post("/policies/{policy_id}/versions")
def save_policy_version(
    policy_id: str,
    body: SavePolicyRequest,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    store = _store(streams, policy_id)
    try:
        version = store.save(policy_id, body.content, body.note, principal.user_id, load_sample())
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"version": version}


class ActivateRequest(BaseModel):
    version: int


@router.post("/policies/{policy_id}/activate")
def activate_policy_version(
    policy_id: str,
    body: ActivateRequest,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    store = _store(streams, policy_id)
    try:
        return store.activate(policy_id, body.version, principal.user_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


# --- House universe ---


class UniverseRequest(BaseModel):
    source: Literal["sample", "portfolio"]


@router.get("/universe")
def get_universe(streams: StreamStore = Depends(get_stream_store)) -> dict:
    """Which companies the house program covers, and how many each source has."""
    sample = load_sample(votes=[], alerts=[])
    return {**HouseUniverseSetting(streams.root).get(), "issuers": len(sample["issuers"]), "note": sample.get("note")}


@router.put("/universe")
def put_universe(
    body: UniverseRequest, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    try:
        HouseUniverseSetting(streams.root).set(body.source, principal.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return get_universe(streams)


# --- Monitoring triggers ---


@router.get("/studio/monitoring/triggers")
def monitoring_triggers(
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """Triggers raised by the active monitoring rules on company data, matched to open engagements."""
    sample, records = load_sample(), engagements.list_all()
    return {"triggers": monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, records)}


@router.get("/triggers")
def list_stored_triggers(
    status: Literal["open", "acknowledged", "resolved"] | None = None,
    streams: StreamStore = Depends(get_stream_store),
) -> dict:
    store = TriggerStore(streams.root)
    names = store.companies()
    return {"triggers": [{**t.model_dump(), "company": names.get(t.trigger_id, "")} for t in store.list_triggers(status)]}


class TriggerTransitionRequest(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]
    decided_by: str
    reason: str = ""


@router.post("/triggers/{trigger_id}/transition")
def post_trigger_transition(
    trigger_id: str,
    body: TriggerTransitionRequest,
    streams: StreamStore = Depends(get_stream_store),
) -> dict:
    try:
        return TriggerStore(streams.root).transition(trigger_id, body.status, body.decided_by, body.reason).model_dump()
    except KeyError as exc:
        raise HTTPException(404, "Unknown trigger") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class OpenFromTriggerRequest(BaseModel):
    issuer_id: str
    rule: str


@router.post("/monitoring/open-engagement")
def open_engagement_from_trigger(
    body: OpenFromTriggerRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Opens an engagement for a trigger the active rules raise, or one a monthly run stored. The theme and
    severity come from the rule, not the request."""
    sample = load_sample()
    records = engagements.list_all()
    triggers = monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, records)
    trigger = next((t for t in triggers if t["issuer_id"] == body.issuer_id and t["rule"] == body.rule), None)
    if trigger is None and (stored := TriggerStore(streams.root).stored_trigger(trigger_id(body.issuer_id, body.rule))):
        trigger = {**stored, "engagement_id": monitoring.open_engagements(records).get((stored["issuer_id"], stored["theme"]))}
    if trigger is None:
        raise HTTPException(404, "No active monitoring rule or monthly run raised such a trigger")
    if trigger["engagement_id"] is not None:
        raise HTTPException(409, f"Already attached to engagement {trigger['engagement_id']}")
    _, issue = engagements.open_issue(
        trigger["issuer_id"],
        trigger["company"],
        theme=trigger["theme"],
        severity=IssueSeverity(trigger["severity"]),
        source=TriggerSource.MONITORING_RULE,
        source_detail=f"{trigger['rule']}: {trigger['reason']} (opened by {principal.name})",
        sector=trigger["sector"],
    )
    return {"issue_id": issue.issue_id, "trigger": {**trigger, "engagement_id": issue.issue_id}}


# --- Stewardship report (House Deck PPTX) ---


def _deck_response(build, data, filename: str, background: BackgroundTasks) -> FileResponse:
    """`build(data, path, pdf=False)` into a temp dir that is removed once the file is sent."""
    tmp = Path(tempfile.mkdtemp(prefix="arp_deck_"))
    try:
        path = build(data, tmp / filename, pdf=False)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    background.add_task(shutil.rmtree, tmp, ignore_errors=True)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@router.get("/report")
def get_house_report(
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    return client_report(streams.root, "House programme", engagements.list_all())


@router.get("/report.pptx")
def get_house_report_pptx(
    background: BackgroundTasks,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> FileResponse:
    """The house stewardship summary as a PowerPoint deck, rendered on request."""
    report = client_report(streams.root, "House programme", engagements.list_all())
    return _deck_response(build_pptx, report, "house-stewardship-report.pptx", background)


# --- Outreach drafts (E6 tags, E8 style check, four-eyes approval) ---


def _drafts(streams: StreamStore) -> drafting.DraftStore:
    return drafting.DraftStore(streams.root)


def _blocklist(streams: StreamStore) -> dict:
    return PolicyStore(streams.root).active("phrase_blocklist")


class StyleCheckRequest(BaseModel):
    text: str


@router.post("/style/check")
def post_style_check(body: StyleCheckRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    """E8: blocklisted phrases in a text, with where they are. Flags only."""
    return {"flags": style_check(body.text, _blocklist(streams))}


@router.get("/drafts")
def list_drafts(streams: StreamStore = Depends(get_stream_store)) -> dict:
    return {"drafts": _drafts(streams).list()}


class CreateDraftRequest(BaseModel):
    company_id: str
    issue_id: str
    type: CorrespondenceType = CorrespondenceType.LETTER
    text: str
    interaction_type: InteractionType | None = None


@router.post("/drafts")
def create_draft(
    body: CreateDraftRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        return drafting.create(_drafts(streams), engagements, _blocklist(streams), **body.model_dump(), created_by=principal.user_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class UpdateDraftRequest(BaseModel):
    text: str | None = None
    interaction_type: InteractionType | None = None


@router.put("/drafts/{draft_id}")
def update_draft(
    draft_id: str,
    body: UpdateDraftRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        return drafting.update(_drafts(streams), engagements, _blocklist(streams), draft_id, **body.model_dump(), updated_by=principal.user_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown draft or engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class ApproveDraftRequest(BaseModel):
    note: str = ""


@router.post("/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    body: ApproveDraftRequest,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Four-eyes checkpoint for outreach: nothing is sent before a second person approves it."""
    try:
        return drafting.approve(_drafts(streams), draft_id, principal.user_id, body.note)
    except KeyError as exc:
        raise HTTPException(404, "Unknown draft") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class SentRequest(BaseModel):
    pass


@router.post("/drafts/{draft_id}/sent")
def mark_draft_sent(
    draft_id: str,
    body: SentRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Records that an approved draft went out: it is logged as correspondence with its interaction type."""
    try:
        return drafting.mark_sent(_drafts(streams), engagements, draft_id, principal.user_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown draft or engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# --- Closing engagements & E7 case studies ---


class CloseRequest(BaseModel):
    company_id: str
    issue_id: str
    status: Literal["resolved", "closed"]
    outcome: str


@router.post("/close")
def close_engagement(
    body: CloseRequest,
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        case_study.close(engagements, body.company_id, body.issue_id, IssueStatus(body.status), body.outcome, principal.name)
    except KeyError as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"issue_id": body.issue_id, "status": body.status}


@router.get("/case-study/{company_id}/{issue_id}")
def get_case_study(
    company_id: str,
    issue_id: str,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """E7: a case study compiled from a closed engagement's records, with its E8 style flags."""
    record = engagements.get(company_id)
    if record is None:
        raise HTTPException(404, "Unknown engagement")
    try:
        return case_study.case_study(record, issue_id, _blocklist(streams))
    except KeyError as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
