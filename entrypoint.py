import glob
import hashlib
import os
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import shutil
import urllib.request
import semver  # type: ignore[import-not-found]
import yaml  # type: ignore[import-not-found]


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def get_input(name: str, default: str | None = None, *, required: bool = False) -> str:
    key = f"INPUT_{name.upper()}"
    val = os.environ.get(key)
    if val is None or val == "":
        if required and default is None:
            raise ValueError(f"Missing required input: {name} (env {key})")
        return default or ""
    return val


def truthy(s: str) -> bool:
    return s.strip().lower() in {"1", "true", "yes", "y", "on"}


def ensure_v_prefix(version: str) -> str:
    v = version.strip()
    if not v:
        raise ValueError("helm_version is empty")
    return v if v.startswith("v") else f"v{v}"


def validate_version(version: str) -> bool:
    try:
        semver.VersionInfo.parse(version.strip())
        return True
    except ValueError:
        return False


def detect_arch() -> str:
    # GitHub-hosted Linux runners are typically amd64; arm64 is increasingly common.
    m = os.uname().machine.lower()
    if m in {"x86_64", "amd64"}:
        return "amd64"
    if m in {"aarch64", "arm64"}:
        return "arm64"
    raise RuntimeError(f"Unsupported CPU architecture for Helm binary: {m}")


def download(url: str, dest_path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "package-helm-action"})
    with urllib.request.urlopen(req) as resp, open(dest_path, "wb") as f:
        f.write(resp.read())


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_sha256_file(path: str) -> str:
    # Helm .sha256 files are usually either:
    # - "<hash>  <filename>"
    # - "<hash>"
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read().strip()
    if not txt:
        raise RuntimeError("Empty sha256 file")
    first_token = txt.split()[0].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", first_token):
        raise RuntimeError(f"Invalid sha256 content: {txt[:120]}")
    return first_token.lower()


def run(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        # Fallback for local runs.
        print(f"{name}={value}")
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def resolve_path(workspace: str, p: str) -> str:
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(workspace, p))


def workspace_relpath(workspace: str, p: str) -> str:
    """
    Prefer a workspace-relative path for outputs.

    Docker actions run inside a container where the workspace is typically
    mounted at `/github/workspace`, but subsequent workflow steps run on the
    host runner. Returning a path relative to the repository workspace is more
    portable.
    """
    ws = os.path.normpath(workspace)
    pp = os.path.normpath(p)
    try:
        return os.path.relpath(pp, ws)
    except ValueError:
        # Different drive / unrelated path on some platforms.
        return pp


def parse_values_files(values_files_raw: str) -> list[str]:
    """
    Parse comma- and/or newline-separated file list.
    """
    items: list[str] = []
    for part in re.split(r"[,\n\r]+", values_files_raw or ""):
        p = part.strip()
        if p:
            items.append(p)
    return items


def deep_merge_values(base: object, override: object) -> object:
    """
    Deep-merge YAML values.

    Rules:
    - dict + dict: recursive merge
    - otherwise (scalars, lists, mismatched types): replace with override
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged: dict[object, object] = dict(base)
        for k, v in override.items():
            if k in merged:
                merged[k] = deep_merge_values(merged[k], v)
            else:
                merged[k] = v
        return merged
    return override


def load_yaml_file(path: str) -> object:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {} if data is None else data


def dump_yaml_file(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            default_flow_style=False,
            sort_keys=False,
        )


def build_helm_package_cmd(
    *,
    chart_path: str,
    destination: str,
    helm_chart_version: str,
    helm_chart_app_version: str,
    package_args: str,
) -> list[str]:
    cmd = [
        "helm",
        "package",
        chart_path,
        "--destination",
        destination,
        "--version",
        helm_chart_version,
        "--app-version",
        helm_chart_app_version,
    ]
    extra = shlex.split(package_args) if package_args.strip() else []
    cmd.extend(extra)
    return cmd


def install_helm(helm_version: str) -> None:
    version = ensure_v_prefix(helm_version)
    arch = detect_arch()
    platform = "linux"

    filename = f"helm-{version}-{platform}-{arch}.tar.gz"
    url = f"https://get.helm.sh/{filename}"
    sha_url = f"{url}.sha256"

    with tempfile.TemporaryDirectory(prefix="helm-install-") as td:
        tar_path = os.path.join(td, filename)
        sha_path = tar_path + ".sha256"

        eprint(f"Downloading Helm {version} ({platform}/{arch})...")
        download(url, tar_path)
        download(sha_url, sha_path)

        expected = parse_sha256_file(sha_path)
        actual = sha256_file(tar_path)
        if actual != expected:
            raise RuntimeError(
                "Helm tarball sha256 mismatch. "
                f"expected={expected} actual={actual} url={url}"
            )

        eprint("Extracting Helm...")
        with tarfile.open(tar_path, "r:gz") as tf:
            member_path = f"{platform}-{arch}/helm"
            try:
                member = tf.getmember(member_path)
            except KeyError as ex:
                raise RuntimeError(f"Helm archive missing {member_path}") from ex
            tf.extract(member, path=td)
            helm_src = os.path.join(td, member_path)

        helm_dst = "/usr/local/bin/helm"
        with open(helm_src, "rb") as src, open(helm_dst, "wb") as dst:
            dst.write(src.read())
        os.chmod(helm_dst, 0o755)

    ver = run(["helm", "version", "--short"])
    if ver.returncode != 0:
        raise RuntimeError(f"Helm installed but failed to run:\n{ver.stdout}")
    eprint(ver.stdout.strip())


def main() -> int:
    try:
        workspace = os.environ.get("GITHUB_WORKSPACE", "/github/workspace")

        chart_path_in = get_input("chart_path", required=True)
        destination_in = get_input("destination", default=".")
        helm_version = get_input("helm_version", default="v3.14.4")
        dependency_update = truthy(get_input("dependency_update", default="false"))
        package_args_in = get_input("package_args", default="")
        helm_chart_version = get_input("helm_chart_version", required=True)
        helm_chart_app_version = get_input("helm_chart_app_version", required=True)
        values_files_raw = get_input("values_files", default="")

        if not validate_version(helm_chart_version):
            raise RuntimeError(f"Invalid helm chart version (SemVer required): {helm_chart_version}")

        chart_path = resolve_path(workspace, chart_path_in)
        destination = resolve_path(workspace, destination_in)

        chart_yaml = os.path.join(chart_path, "Chart.yaml")
        if not os.path.isfile(chart_yaml):
            raise RuntimeError(f"`Chart.yaml` not found at: {chart_yaml}")

        os.makedirs(destination, exist_ok=True)

        install_helm(helm_version)

        values_files = parse_values_files(values_files_raw)
        chart_path_for_packaging = chart_path
        if values_files:
            eprint(f"Merging values files: {', '.join(values_files)}")
            merged_values: object = {}
            for rel in values_files:
                src_path = os.path.normpath(os.path.join(chart_path, rel))
                if not os.path.isfile(src_path):
                    raise RuntimeError(f"Values file not found: {src_path}")
                merged_values = deep_merge_values(merged_values, load_yaml_file(src_path))

            tmp_root = tempfile.mkdtemp(prefix=".dist-temporary-", dir=workspace)
            chart_name = os.path.basename(os.path.normpath(chart_path))
            tmp_chart = os.path.join(tmp_root, chart_name)
            shutil.copytree(chart_path, tmp_chart)

            dump_yaml_file(os.path.join(tmp_chart, "values.yaml"), merged_values)
            chart_path_for_packaging = tmp_chart

        if dependency_update:
            eprint("Running helm dependency update...")
            dep = run(["helm", "dependency", "update", chart_path_for_packaging])
            if dep.returncode != 0:
                raise RuntimeError(f"`helm dependency update` failed:\n{dep.stdout}")

        cmd = build_helm_package_cmd(
            chart_path=chart_path_for_packaging,
            destination=destination,
            helm_chart_version=helm_chart_version,
            helm_chart_app_version=helm_chart_app_version,
            package_args=package_args_in,
        )

        eprint(f"Running: {' '.join(shlex.quote(c) for c in cmd)}")
        res = run(cmd)
        if res.returncode != 0:
            raise RuntimeError(f"`helm package` failed:\n{res.stdout}")

        out = res.stdout
        m = re.search(r"saved it to:\s*(.+)\s*$", out, flags=re.IGNORECASE | re.MULTILINE)
        package_path = None
        if m:
            package_path = m.group(1).strip()
        else:
            # Fallback: pick the newest tgz in destination.
            tgzs = glob.glob(os.path.join(destination, "*.tgz"))
            if tgzs:
                tgzs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                package_path = tgzs[0]

        if not package_path:
            raise RuntimeError(
                "Could not determine created package path from Helm output.\n"
                f"Output:\n{out}"
            )

        # Normalize to an absolute path within the workspace when possible.
        package_path_abs = resolve_path(workspace, package_path) if not os.path.isabs(package_path) else os.path.normpath(package_path)
        package_path_out = workspace_relpath(workspace, package_path_abs)

        eprint(f"Package created: {package_path_abs}")
        write_output("package_path", package_path_out)
        return 0
    except Exception as ex:
        eprint(f"ERROR: {ex}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

