"""showcase-stewardship-fixes PR B, the "unit (browser)" rows: the running app with the named API routes stubbed."""

import json
import os
import re
import uuid

import httpx
import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")  # the stack's API (e2e_stack.sh)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

ANA = {"user_id": "u_ana", "name": "Ana", "role": "approver"}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        page.route("**/api/me", lambda r: r.fulfill(json=ANA))
        page.add_init_script("localStorage.setItem('arp.reviewer', 'Ana')")  # the voting reviewer is typed per device
        yield page
        browser.close()


# --- Engagement panel: the same summary twice, letter placeholders (AC-101, AC-155) ---


def _engagement_issue() -> tuple[str, str]:
    company = f"E2E{uuid.uuid4().hex[:6].upper()}"
    httpx.post(f"{API}/api/engagement/records", json={"company_id": company, "name": "Acme Panel"}).raise_for_status()
    res = httpx.post(f"{API}/api/engagement/records/{company}/issues?name=Acme%20Panel", json={"theme": "climate"})
    return company, res.raise_for_status().json()["issue_id"]


def test_outreach_twice_sends_the_same_summary_and_placeholders_show(page):  # AC-101, AC-155
    company, issue_id = _engagement_issue()
    dossier = {"dossier_id": "d1", "company_id": company, "issue_id": issue_id, "generated_at": "2026-11-12T00:00:00+00:00",
               "summary": "s", "controversy_context": "c", "peer_benchmark_notes": "p", "engagement_history_summary": "",
               "recommended_contacts": ["IR"], "citations": [], "confidence": 0.9, "needs_review": False}
    letter = {"subject": "Engagement request from [Fund name]", "body": "Dear IR", "recommended_recipient": "IR",
              "citations": [], "placeholders": ["[Fund name]"]}
    page.route(f"**/issues/{issue_id}/dossier", lambda r: r.fulfill(json={"dossier": dossier, "needs_review": False}))
    page.route(f"**/issues/{issue_id}/outreach-letter", lambda r: r.fulfill(json=letter))
    summaries = []

    def log(route):
        summaries.append(json.loads(route.request.post_data)["summary"])
        route.continue_()

    page.route(f"**/issues/{issue_id}/log-outreach-sent", log)
    page.goto(f"{URL}/#/engagement")
    page.locator("section.card", has_text=f"({company}) issues").locator(".issue-row").click()
    page.get_by_role("button", name="Draft dossier").click()
    page.get_by_role("button", name="Draft outreach letter").click()
    page.get_by_text("Fill in before sending: [Fund name]").wait_for()
    button = page.get_by_role("button", name="Log outreach sent")
    for n in (1, 2):
        button.click()
        page.wait_for_timeout(500)
        assert len(summaries) == n
    assert summaries[0] == summaries[1]


def test_scan_says_which_signals_were_skipped(page):  # AC-111
    page.route("**/api/engagement/trigger-scan", lambda r: r.fulfill(
        json={"events": [], "unlisted_signals": {"count": 3, "company_ids": ["C2", "C3"]}}))
    page.goto(f"{URL}/#/engagement")
    form = page.locator("section", has=page.get_by_role("button", name="Run scan"))
    form.get_by_placeholder("e.g. AAPL").nth(0).fill("C1")  # the company row, then the signal row
    form.get_by_label("Company name").fill("Acme")
    form.get_by_placeholder("e.g. AAPL").nth(1).fill("C2")
    form.get_by_label("Theme").first.fill("climate")
    page.get_by_role("button", name="Run scan").click()
    page.get_by_text("3 signals skipped: their companies are not in the list (C2, C3).").wait_for()


# --- Steward Workflow: chips and four-eyes (AC-141, AC-144) ---


@pytest.fixture
def sample_house_universe():
    """The client program needs house weights; an empty portfolio universe left by another test has none."""
    before = httpx.get(f"{API}/api/stewardship/universe").json()["source"]
    httpx.put(f"{API}/api/stewardship/universe", json={"source": "sample"}).raise_for_status()
    yield
    httpx.put(f"{API}/api/stewardship/universe", json={"source": before}).raise_for_status()


def test_client_program_marks_placeholder_scores(page, sample_house_universe):  # AC-141
    name = f"Client {uuid.uuid4().hex[:4]}"
    httpx.post(f"{API}/api/stewardship/streams", json={"name": name}).raise_for_status()
    note = "CLTI scores are placeholders, not an assessment of these companies. Do not share this as a view on them."

    def program(route):  # the sample benchmark has no score note; portfolio holdings do
        if route.request.method != "GET":
            return route.fallback()
        response = route.fetch()
        body = response.json()
        if "simulation" in body:  # the house stream has no client program
            body["simulation"]["score_note"] = note
        route.fulfill(response=response, json=body)

    page.route(re.compile(r".*/api/stewardship/streams/[^/]+/program$"), program)
    page.goto(f"{URL}/#/stewardship/program")
    page.get_by_label("Program", exact=True).select_option(label=name)  # ui-trim-workspaces: one Program select
    page.locator(".warning-banner", has_text="CLTI scores are placeholders").wait_for()
    banner = page.locator(".warning-banner", has_text="CLTI scores are placeholders")
    assert banner.locator(".chip-sample").count() == 1 and banner.inner_text().startswith("Sample data")
    tile = lambda label: page.locator(".metric-tile", has_text=label)  # noqa: E731
    assert tile("Weighted CLTI").locator(".chip-sample").count() == 1
    assert tile("Active share").locator(".chip-sample").count() == 0


def test_outreach_draft_by_the_signed_in_author_says_a_second_person_is_needed(page):  # AC-144
    item = {"kind": "outreach", "draft_id": "dr1", "company": "Acme", "theme": "climate", "type": "letter",
            "interaction_type": "dialogue", "proposed_interaction_type": "dialogue", "proposed_because": "x",
            "text": "Dear board", "style_flags": [], "authors": ["Ana"]}

    def flow(route):
        body = route.fetch().json()
        for stage in body["stages"]:
            if stage["id"] == "checkpoint":
                stage["decisions"] = [item, *stage.get("decisions", [])]
        route.fulfill(json=body)

    page.route("**/api/stewardship/streams/house/flow", flow)
    page.goto(f"{URL}/#/stewardship/checkpoint")
    button = page.get_by_role("button", name="Approve for sending")
    button.wait_for()
    assert button.is_disabled()
    page.get_by_text(
        "A second person is needed: this draft was written by Ana, and someone who did not write it approves it."
    ).wait_for()


# --- RFP four-eyes (AC-145) ---


def test_rfp_answer_edited_last_by_the_approver_says_a_second_person_is_needed(page):  # AC-145
    question = {"id": 7, "location": "Q1", "answer_location": "B2", "question": "Do you vote?", "answer": "Yes",
                "status": "draft", "flags": [], "assignee": None, "last_editor": "u_ana", "sources": []}
    project = {"id": 1, "investor": "Nordic Pension Fund", "due_date": None, "filename": "rfp_in.xlsx", "run_status": "done",
               "not_located": 0, "question_count": 1, "approved_count": 0, "questions": [question]}
    page.route("**/api/rfp/projects/1", lambda r: r.fulfill(json=project))
    page.goto(f"{URL}/#/rfp/1")
    page.get_by_text("A second person is needed: you edited this answer last, and another approver must approve it.").wait_for()
    assert page.get_by_role("button", name="Approve", exact=True).count() == 0
