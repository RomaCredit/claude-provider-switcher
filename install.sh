#!/bin/sh
set -eu

version="${CLAUDE_SWITCHER_VERSION:-v0.1.0}"
if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required." >&2
  exit 1
fi
python3 -c 'import re,sys; sys.exit(not bool(re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", sys.argv[1])))' "$version" || {
  echo "Version must be a release tag such as v0.1.0." >&2
  exit 1
}
if [ "$(id -u)" -eq 0 ]; then
  bin_dir="${CLAUDE_SWITCHER_BIN_DIR:-/usr/local/bin}"
  data_dir="${CLAUDE_SWITCHER_DATA_DIR:-/usr/local/lib/claude-provider-switcher}"
else
  bin_dir="${CLAUDE_SWITCHER_BIN_DIR:-$HOME/.local/bin}"
  data_dir="${CLAUDE_SWITCHER_DATA_DIR:-$HOME/.local/share/claude-provider-switcher}"
fi
temporary=$(mktemp -d)
trap 'rm -f "$temporary/source.zip"; rmdir "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
url="https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/$version.zip"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$url" -o "$temporary/source.zip"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$temporary/source.zip" "$url"
else
  echo "curl or wget is required." >&2
  exit 1
fi
python3 - "$temporary/source.zip" "$version" "$bin_dir" "$data_dir" <<'PY'
import ast
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
import tempfile
import zipfile

archive, version, bin_value, data_value = sys.argv[1:]
bin_dir, data_dir = Path(bin_value).resolve(), Path(data_value).resolve()
try:
    for name in ("ccs", "claude-provider-switcher"):
        if (bin_dir / name).exists():
            text = (bin_dir / name).read_text(encoding="utf-8")
            if "# claude-provider-switcher standalone launcher" not in text:
                raise ValueError("An unrelated command already uses the installation path.")
    prefix = f"claude-provider-switcher-{version[1:]}/"
    sources = {}
    with zipfile.ZipFile(archive) as package:
        if sum(i.file_size for i in package.infolist()) > 10 * 1024 * 1024:
            raise ValueError("Archive too large.")
        for entry in package.infolist():
            if not entry.filename.startswith(prefix):
                raise ValueError("Unexpected archive root.")
            relative = entry.filename[len(prefix):]
            path = PurePosixPath(relative)
            if relative == "ccs.py" or (len(path.parts) == 2 and path.parts[0] == "claude_provider_switcher" and path.suffix == ".py"):
                if relative in sources or "\\" in relative or path.is_absolute() or ".." in path.parts:
                    raise ValueError("Unsafe archive entry.")
                text = package.read(entry).decode("utf-8")
                ast.parse(text)
                sources[relative] = text
    initializer = ast.parse(sources["claude_provider_switcher/__init__.py"])
    actual = next(n.value.value for n in initializer.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
    if actual != version[1:] or "ccs.py" not in sources or "claude_provider_switcher/cli.py" not in sources:
        raise ValueError("Release version or entry point mismatch.")
    bin_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    release = Path(tempfile.mkdtemp(prefix=version + "-", dir=data_dir))
    release.chmod(0o755)
    for relative, text in sources.items():
        output = release / relative
        output.parent.mkdir(exist_ok=True)
        output.write_text(text, encoding="utf-8")
        output.chmod(0o644)
    launcher = "#!/bin/sh\n# claude-provider-switcher standalone launcher\nexec " + shlex.join([sys.executable, str(release / "ccs.py")]) + ' "$@"\n'
    for name in ("ccs", "claude-provider-switcher"):
        fd, temporary = tempfile.mkstemp(prefix=".ccs-", dir=bin_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(launcher)
            os.chmod(temporary, 0o755)
            os.replace(temporary, bin_dir / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(f"Installed {version}: {bin_dir / 'ccs'}")
    print("Both ccs and claude-provider-switcher are available. No Claude settings were changed.")
    if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f'For this shell: export PATH={shlex.quote(str(bin_dir))}:"$PATH"')
    print("Run: ccs --version")
except (OSError, ValueError, KeyError, StopIteration, SyntaxError, zipfile.BadZipFile):
    print("Installation failed: invalid archive, command collision or filesystem error. Check permissions and release tag.", file=sys.stderr)
    sys.exit(1)
PY
