"""Themed dialogs on every page (no browser alert/confirm/prompt) and the free-trial counter."""
import datetime
import os
import re

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")


def test_every_page_has_the_themed_dialogs(d, client):
    for url in ("/drone-control", "/drone-grid", "/settings", "/users"):
        html = client.get(url).get_data(as_text=True)
        assert html.count('id="uiDialogJs"') == 1, url
        assert html.find("uiDialogJs") < html.find("</head>") or "</head>" not in html  # defined before the page's scripts


def test_no_browser_popups_left_in_page_code():
    calls = re.compile(r"(?<![\w.])(alert|confirm|prompt)\(")
    for root, _, files in os.walk(APP):
        for f in files:
            if f.endswith((".py", ".pyw", ".js", ".html")) and f != "dialogs.py":
                text = open(os.path.join(root, f), encoding="utf-8").read()
                found = [m.group(0) for m in calls.finditer(text)
                         if not text[max(0, m.start() - 4):m.start()].endswith("def ")]
                assert not found, (f, found)


def test_trial_counter_only_on_a_trial(d, client):
    saved = dict(d.cloud_state)
    onprem = d.onprem_mode
    try:
        d.onprem_mode = lambda: False
        ends = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=20)).isoformat()
        d.cloud_state.update(organization_status="trial", trial_ends_at=ends)
        html = client.get("/drone-control").get_data(as_text=True)
        assert 'id="trialPill"' in html and "Free trial ends tomorrow" in html and d.CHOOSE_PLAN_URL in html
        d.cloud_state.update(organization_status="active")
        assert 'id="trialPill"' not in client.get("/drone-control").get_data(as_text=True)
        d._apply_license({"organization_status": "trial", "features": {}, "trial_ends_at": ends}, True, 0)
        assert d.trial_ends_ms() and abs(d.trial_ends_ms() / 1000 - datetime.datetime.fromisoformat(ends).timestamp()) < 1
    finally:
        d.onprem_mode = onprem
        d.cloud_state.clear()
        d.cloud_state.update(saved)
