"""Runs cargo with the Visual Studio C++ build tools environment loaded, so linking works from any shell.

  python cargo_vs.py <crate folder> <cargo arguments...>
  python cargo_vs.py C:/x/MyApp.Rust test --test api queue

cargo on Windows needs link.exe and the Windows SDK libraries on the path. This finds vcvars64.bat (vswhere, else the Build Tools folders under Program Files)
and runs `cargo` in the crate folder after it. cargo itself is found on PATH or in ~/.cargo/bin. The exit code is cargo's. For a long build, wrap it:
python run_logged.py <log> -- python cargo_vs.py <folder> test
"""
import os
import subprocess
import sys
from pathlib import Path

VCVARS = r"VC\Auxiliary\Build\vcvars64.bat"


def find_vcvars():
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        result = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                                capture_output=True, text=True)
        path = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if path and (Path(path) / VCVARS).is_file():
            return Path(path) / VCVARS
    for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        for candidate in sorted(Path(root or ".").glob("Microsoft Visual Studio/*/*/" + VCVARS), reverse=True):
            return candidate
    sys.exit("vcvars64.bat not found: install the Visual Studio Build Tools with the C++ workload")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    folder, arguments = sys.argv[1], sys.argv[2:]
    if not Path(folder).is_dir():
        sys.exit(f"{folder} is not a folder")
    env = os.environ.copy()
    env["PATH"] = str(Path.home() / ".cargo" / "bin") + os.pathsep + env["PATH"]
    quoted = " ".join(f'"{a}"' if " " in a else a for a in arguments)
    command = f'call "{find_vcvars()}" >nul 2>&1 && cargo {quoted}'
    # one string, so cmd receives the quotes around the vcvars path as they are
    sys.exit(subprocess.run(f'cmd /c "{command}"', cwd=folder, env=env).returncode)


if __name__ == "__main__":
    main()
