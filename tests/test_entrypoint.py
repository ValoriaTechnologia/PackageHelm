import os
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import entrypoint


def test_truthy():
    assert entrypoint.truthy("true") is True
    assert entrypoint.truthy("TRUE") is True
    assert entrypoint.truthy("1") is True
    assert entrypoint.truthy("yes") is True
    assert entrypoint.truthy("on") is True
    assert entrypoint.truthy("false") is False
    assert entrypoint.truthy("0") is False
    assert entrypoint.truthy("no") is False


def test_ensure_v_prefix():
    assert entrypoint.ensure_v_prefix("v3.14.4") == "v3.14.4"
    assert entrypoint.ensure_v_prefix("3.14.4") == "v3.14.4"


def test_validate_version_semver():
    assert entrypoint.validate_version("1.2.3") is True
    assert entrypoint.validate_version("0.0.0") is True
    assert entrypoint.validate_version("1.2.3-alpha.1") is True
    assert entrypoint.validate_version("1.2.3+build.5") is True
    assert entrypoint.validate_version("1.2.3-alpha.1+build.5") is True

    assert entrypoint.validate_version("") is False
    assert entrypoint.validate_version("1.2") is False
    assert entrypoint.validate_version("01.2.3") is False
    assert entrypoint.validate_version("1.02.3") is False
    assert entrypoint.validate_version("1.2.03") is False


def test_parse_sha256_file_accepts_hash_only(tmp_path):
    h = "a" * 64
    p = tmp_path / "file.sha256"
    p.write_text(h + "\n", encoding="utf-8")
    assert entrypoint.parse_sha256_file(str(p)) == h


def test_parse_sha256_file_accepts_hash_and_filename(tmp_path):
    h = "b" * 64
    p = tmp_path / "file.sha256"
    p.write_text(f"{h}  helm-v3.14.4-linux-amd64.tar.gz\n", encoding="utf-8")
    assert entrypoint.parse_sha256_file(str(p)) == h


def test_resolve_path_relative():
    ws = "/ws"
    assert entrypoint.resolve_path(ws, "charts/my") == os.path.normpath("/ws/charts/my")


def test_resolve_path_absolute_passthrough():
    ws = "/ws"
    assert entrypoint.resolve_path(ws, "/abs/path") == os.path.normpath("/abs/path")


def test_workspace_relpath_under_workspace():
    ws = "/github/workspace"
    assert entrypoint.workspace_relpath(ws, "/github/workspace/dist/x.tgz") == os.path.normpath(
        "dist/x.tgz"
    )


def test_build_helm_package_cmd_includes_versions_and_args():
    cmd = entrypoint.build_helm_package_cmd(
        chart_path="/ws/chart",
        destination="/ws/dist",
        helm_chart_version="1.2.3",
        helm_chart_app_version="4.5.6",
        package_args="--dependency-update --debug",
    )
    assert cmd[:4] == ["helm", "package", "/ws/chart", "--destination"]
    assert "--version" in cmd
    assert cmd[cmd.index("--version") + 1] == "1.2.3"
    assert "--app-version" in cmd
    assert cmd[cmd.index("--app-version") + 1] == "4.5.6"
    assert "--dependency-update" in cmd
    assert "--debug" in cmd


def test_parse_values_files():
    assert entrypoint.parse_values_files("") == []
    assert entrypoint.parse_values_files("values.yaml") == ["values.yaml"]
    assert entrypoint.parse_values_files("values.yaml,values.dev.yaml") == [
        "values.yaml",
        "values.dev.yaml",
    ]
    assert entrypoint.parse_values_files("values.yaml\nvalues.dev.yaml\n") == [
        "values.yaml",
        "values.dev.yaml",
    ]


def test_deep_merge_values_dict_merge_and_list_replace():
    base = {"a": 1, "nested": {"x": 1, "keep": "k"}, "lst": [1, 2]}
    override = {"nested": {"x": 9, "y": 2}, "lst": [3], "b": 2}
    merged = entrypoint.deep_merge_values(base, override)
    assert merged == {
        "a": 1,
        "b": 2,
        "nested": {"x": 9, "y": 2, "keep": "k"},
        "lst": [3],
    }

