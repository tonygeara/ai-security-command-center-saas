"""Every module of the app must be in both Windows packages. The on-prem build (build_onprem.ps1) copies and compiles
a fixed list of modules, and the PyInstaller specs list hidden imports: a module missing there is missing from the
installed app, which then fails to start (V11.10.0's on-prem build missed the dock modules)."""
import ast
import os
import re

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
INSTALLER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "installer")
GENERATED = {"edition"}  # written by the build itself


def _local_imports(path, local):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found & local


def app_modules():
    """The app's own modules the dashboard and launcher need, following imports between them."""
    local = {f[:-3] for f in os.listdir(APP) if f.endswith(".py")} | {"pages"}
    todo, seen = ["dashboard", "launcher"], set()
    while todo:
        m = todo.pop()
        if m in seen or m == "pages":
            seen.add(m)
            continue
        seen.add(m)
        path = os.path.join(APP, m + (".pyw" if m == "launcher" else ".py"))
        todo += sorted(_local_imports(path, local) - seen)
    return seen - {"dashboard", "launcher", "pages"}


def _read(name):
    with open(os.path.join(INSTALLER, name), encoding="utf-8") as f:
        return f.read()


def test_onprem_build_includes_every_module():
    ps = _read("build_onprem.ps1")
    copy = re.search(r"foreach \(\$m in ([^)]*)\) \{ Copy-Item", ps).group(1)
    compiled = re.search(r"foreach \(\$m in ([^)]*)\) \{\s*Write-Host \"Compiling", ps).group(1)
    own = re.search(r"\$own = (.*)", ps).group(1)
    names = lambda s: set(re.findall(r"'(\w+)'", s))  # noqa: E731
    copied = names(copy) | {"licensing", "browser_mode", "docker_setup"}  # copied one by one above the loop
    need = app_modules() - GENERATED
    assert not need - copied, f"build_onprem.ps1 doesn't copy: {sorted(need - copied)}"
    # Compiled to native code (browser_mode stays Python, like the launcher).
    py = {"browser_mode", "docker_setup"}  # stay Python, like the launcher
    assert not (need - py) - names(compiled), f"build_onprem.ps1 doesn't compile: {sorted((need - py) - names(compiled))}"
    assert not (need - py - {"edition"}) - names(own), f"build_onprem.ps1 leak check misses: {sorted((need - py) - names(own))}"


def test_onprem_spec_lists_every_module():
    """On-prem, the dashboard is compiled, so PyInstaller can't see its imports: each must be a hidden import.
    (The standard edition packages dashboard.py itself, so PyInstaller finds them there.)"""
    listed = set(re.findall(r"'(\w+)'", _read("onprem.spec")))
    missing = app_modules() - listed
    assert not missing, f"onprem.spec hiddenimports miss: {sorted(missing)}"


def test_installer_never_kills_its_own_process_tree():
    """A self-update starts Setup from the running program, so Setup is that program's child: stopping the program
    with taskkill /T (the whole tree) made Setup kill itself and the PC was left stopped and not updated."""
    iss = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "installer", "installer.iss"), encoding="utf-8").read()
    kills = [line for line in iss.splitlines() if "taskkill" in line.lower() and not line.strip().startswith("{")]
    assert kills and all("/T" not in line.upper().split("'")[3] for line in kills if "Exec(" in line), kills
