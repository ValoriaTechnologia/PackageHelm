# Package Helm chart (GitHub Action)

A **Docker-based GitHub Action (Linux runners only)** that:
- downloads and installs Helm
- runs `helm package` on a chart directory
- outputs the resulting `.tgz` path as `package_path`

## Usage

```yaml
jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Package Helm chart
        id: pkg
        uses: <owner>/<repo>@v1
        with:
          chart_path: ./path/to/chart
          values_files: |
            values.yaml
            values.dev.yaml
          destination: ./dist
          helm_version: v3.14.4
          dependency_update: "true"
          helm_chart_version: 1.2.3
          helm_chart_app_version: 1.2.3
          package_args: ""

      - name: Show package path
        run: echo "Package: ${{ steps.pkg.outputs.package_path }}"
```

## Inputs

- **`chart_path`** (required): Path to a Helm chart directory containing `Chart.yaml`.
- **`destination`** (optional, default `.`): Directory where the packaged `.tgz` will be written.
- **`helm_version`** (optional, default `v3.14.4`): Helm version tag to install.
- **`dependency_update`** (optional, default `false`): If `true`, runs `helm dependency update` before packaging.
- **`helm_chart_version`** (required): Chart version passed to `helm package --version`.
- **`helm_chart_app_version`** (required): App version passed to `helm package --app-version`.
- **`values_files`** (optional): List of values files to merge **in order** (comma and/or newline separated). Paths are relative to `chart_path`. The merged result is embedded as `values.yaml` in the packaged chart.
- **`package_args`** (optional): Extra arguments appended to `helm package`.

## Outputs

- **`package_path`**: Path to the created `.tgz` file (workspace-relative).

## Notes

- **Runner support**: Linux only (e.g. `ubuntu-latest`) because this is a Docker action.
- **Chart path**: Provide paths relative to the repository root after `actions/checkout`.

## Publishing / versioning

Releases are created **automatically** on push to `main` using [mathieudutour/github-tag-action](https://github.com/mathieudutour/github-tag-action). The next SemVer tag is computed from **conventional commits**:

- `fix:` or `fix(scope):` → **patch** (e.g. 1.0.0 → 1.0.1)
- `feat:` or `feat(scope):` → **minor** (e.g. 1.0.0 → 1.1.0)
- `BREAKING CHANGE:` in body or `feat!:` / `fix!:` → **major** (e.g. 1.0.0 → 2.0.0)
- Other commits use the **default bump** (patch)

Each release includes auto-generated notes (changelog) and a **source zip** of the repo at that tag.

Consumers should use `@v1` or a specific tag like `@v1.2.3`.