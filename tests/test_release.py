import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from kidtv.updater import _find_app_root, _safe_extract, version_in

ROOT = Path(__file__).resolve().parents[1]


def test_release_notes_pick_the_right_section(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rn", ROOT / "scripts/release_notes.py")
    rn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rn)
    text = "# Zmeny\n\n## v0.3.0\n- c\n\n## v0.2.0\n- a\n- b\n\n## v0.1.0\n- x\n"
    assert rn.notes_for("v0.2.0", text) == "- a\n- b"
    assert rn.notes_for("v0.1.0", text) == "- x"
    assert rn.notes_for("v9.0.0", text) == ""
    assert rn.notes_for("v0.2.0", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")).startswith("- **Aktualizácie")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_bundle_is_installable(tmp_path):
    out = subprocess.run(["bash", str(ROOT / "scripts/build_bundle.sh"), "v9.8.7", str(tmp_path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    bundle = Path(out)
    assert bundle.name == "kid-tv-app-v9.8.7.tar.gz"
    sha = (tmp_path / (bundle.name + ".sha256")).read_text().split()[0]
    import hashlib
    assert sha == hashlib.sha256(bundle.read_bytes()).hexdigest()
    names = tarfile.open(bundle).getnames()
    assert "kid-tv/scripts/apply-update.sh" in names and not any(n.startswith("kid-tv/tests") for n in names)
    target = tmp_path / "x"
    target.mkdir()
    _safe_extract(bundle, target)
    app = _find_app_root(target)
    assert app and version_in(app) == "9.8.7"
    assert (app / "scripts/apply-update.sh").stat().st_mode & 0o100
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(["bash", str(ROOT / "scripts/build_bundle.sh"), "0.2", str(tmp_path)], check=True,
                       capture_output=True)


def test_setup_keeps_logind_off_the_power_key():
    # The remote's on/off must only put the TV to standby: if logind handled it,
    # the whole Pi would power off and no button could wake it again.
    setup = (Path(__file__).parent.parent / "image" / "setup.sh").read_text(encoding="utf-8")
    for key in ("HandlePowerKey=ignore", "HandleSuspendKey=ignore", "HandleHibernateKey=ignore"):
        assert key in setup
