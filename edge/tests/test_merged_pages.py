"""Duplicates merged (V11.26.0): one Add a drone list, one place for camera positions, Incidents & events together,
Settings' AI switches are the working Dashboard ones, and portal accounts shown on the PC's Users page."""


def test_one_add_a_drone_list(client):
    add = client.get("/drone-add").get_data(as_text=True)
    assert "k:'rtmp',t:'DJI Fly live stream (video only)'" in add and "async function addRtmp" in add and "/api/setup/drones" in add
    wiz = client.get("/setup/add").get_data(as_text=True)
    assert "location.href='/drone-add'" in wiz and 'id="dronePanel"' not in wiz and "location.replace('/drone-add?kind=rtmp')" in wiz
    dash = client.get("/").get_data(as_text=True)
    assert 'location.href = "/drone-add"' in dash and 'fetch("/api/setup/drone", {method: "POST"})' not in dash


def test_settings_ai_switches_are_the_working_ones_and_gps_dispatch_is_gone(client):
    html = client.get("/settings").get_data(as_text=True)
    for x in ('id="aiCam"', 'id="aiDrone"', 'id="aiTrack"', 'id="aiObj"', "'/api/camera/toggle'", "'/api/drone/tracking/toggle'"):
        assert x in html
    assert 'data-key="camera_ai"' not in html and 'data-key="face_ai"' not in html and "GPS dispatch" not in html and 'id="lat"' not in html
    assert client.get("/api/gps-dispatch/status").status_code == 404
    dash = client.get("/").get_data(as_text=True)
    assert "OTHER OBJECTS LIST" in dash and "OBJECT AI •" not in dash
    assert 'location.href = "/settings/events"' in dash  # the Dashboard's Event history opens the one event list
    # The other settings still save from their switches.
    assert client.post("/api/customer/settings", json=client.get("/api/customer/settings").get_json()).get_json()["ok"]


def test_users_page_shows_portal_accounts_when_paired(d, client, monkeypatch):
    j = client.get("/api/users").get_json()
    assert j["portal"] is False and j["portal_users"] == []
    monkeypatch.setattr(d.web_access, "portal_available", lambda: True)
    monkeypatch.setattr(d.web_access, "_portal_load", lambda: {"rami@cedar.example": {"role": "admin", "name": "Rami", "verified": 1700000000,
                                                                                     "hash": "secret", "stamp": "x"}})
    j = client.get("/api/users").get_json()
    assert j["portal"] and j["portal_users"] == [{"email": "rami@cedar.example", "role": "admin", "name": "Rami", "verified": 1700000000}]
    html = client.get("/users").get_data(as_text=True)
    assert 'id="portalPanel"' in html and "Manage users in the portal" in html and "Local accounts (this PC only)" in html


def test_licence_page_wording_and_online_licence(d, client, monkeypatch):
    html = client.get("/license").get_data(as_text=True)
    assert 'id="onlinePanel"' in html and "Install licence file" in html and "license file" not in html.lower()
    r = client.post("/api/license", data="not json")
    assert r.status_code == 400 and r.get_json()["error"] == "That is not a licence file."
    assert client.get("/api/license").get_json()["online"] is None  # an on-prem (licence file) PC
    monkeypatch.setattr(d, "onprem_mode", lambda: False)
    monkeypatch.setattr(d.edition, "EDITION", "saas")
    monkeypatch.setattr(d, "load_edge_agent_config", lambda: {"device_token": "t"})
    with d.cloud_lock:
        saved = dict(d.cloud_state)
        d.cloud_state.update(licensed=True, plan_code="business", organization_status="active", connected=True,
                             features={"camera_ai": {"enabled": True}, "drone_dock": {"enabled": False}})
    try:
        o = client.get("/api/license").get_json()["online"]
        assert o["licensed"] and o["plan"] == "business" and o["features"] == ["camera_ai"]
    finally:
        with d.cloud_lock:
            d.cloud_state.clear()
            d.cloud_state.update(saved)
    import licensing
    assert licensing.verify({"nope": 1})[1] == "Not a licence file."
