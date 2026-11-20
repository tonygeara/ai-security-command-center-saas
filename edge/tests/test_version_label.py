"""The version and the edition are shown at the top right of every page."""


def test_version_top_right(d, client):
    label = d.VERSION_LABEL
    assert label.startswith(d.APP_VERSION) and label.endswith(("ONLINE", "ON-PREM"))
    main = client.get("/").get_data(as_text=True)
    assert f'<div class="app-version" title="Version">{label}</div>' in main and "<!--APP_VERSION-->" not in main
    for path in ("/drone-control", "/settings", "/setup/add"):
        assert label in client.get(path).get_data(as_text=True), path
    assert ".hud-ver" in client.get("/hud.css").get_data(as_text=True)


def test_onprem_label(d):
    import os
    import re
    src = open(os.path.join(os.path.dirname(d.__file__), "dashboard.py"), encoding="utf-8").read()
    line = re.search(r"^VERSION_LABEL = .*$", src, re.M).group(0)
    assert "'ON-PREM' if edition.EDITION == 'onprem'" in line  # the on-prem build sets edition.EDITION = "onprem"
