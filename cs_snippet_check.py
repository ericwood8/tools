"""Compiles a C# snippet in a throwaway project and prints the compiler errors, so a claim about the compiler takes seconds to check.

  python cs_snippet_check.py -e "var a = new[] { };"                      (an error: CS0826)
  python cs_snippet_check.py snippet.cs --run                             (build, then run it and print its output)
  python cs_snippet_check.py -e "..." --package Microsoft.EntityFrameworkCore.Sqlite@10.0.12 --offline
  python cs_snippet_check.py a.cs b.cs --warnings --no-nullable

The code is a full compilation unit: top-level statements work (the project is an executable), and types may follow them.
Each -e or file argument is one source file of the same project.

Options:
  --package ID@VERSION   add a NuGet package (repeat); the version is required so a run is repeatable
  --offline              restore only from the local NuGet cache (NUGET_PACKAGES or ~/.nuget/packages): no download
  --sources A;B          restore from these sources (a folder or a feed URL) instead of the default feeds
  --tfm net10.0          target framework (default net10.0)
  --no-nullable          turn nullable reference types off (default on)
  --no-implicit-usings   turn implicit usings off (default on)
  --lang VERSION         C# language version (default: the SDK's)
  --warnings             also print warnings (default: errors only, plus a warning count)
  --run                  after a good build, run the program (60 s limit) and print what it writes
  --keep                 keep the temporary project and print its folder

Exit codes: 0 build succeeded, 1 compile errors, 2 usage problem or no dotnet SDK, 3 restore failed.
Errors are printed once each as `CODE file(line,col) message`. A restore problem (a missing package) is printed as it is.
The project turns off NuGet audit and the package-version warnings that a throwaway project does not care about.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DIAG = re.compile(r"^(?P<file>.*?)\((?P<line>\d+),(?P<col>\d+)\): (?P<kind>error|warning) (?P<code>[A-Za-z]+\d+): (?P<msg>.*?)(?: \[[^\]]*\])?$")
RESTORE_DIAG = re.compile(r"^(?P<file>.*?\.csproj) ?: (?P<kind>error|warning) (?P<code>NU\d+): (?P<msg>.*?)(?: \[[^\]]*\])?$")


def project_text(args):
    lines = ['<Project Sdk="Microsoft.NET.Sdk">', "  <PropertyGroup>", "    <OutputType>Exe</OutputType>",
             f"    <TargetFramework>{args.tfm}</TargetFramework>",
             f"    <Nullable>{'disable' if args.no_nullable else 'enable'}</Nullable>",
             f"    <ImplicitUsings>{'disable' if args.no_implicit_usings else 'enable'}</ImplicitUsings>",
             "    <NuGetAudit>false</NuGetAudit>", "    <NoWarn>$(NoWarn);NU1603;NU1608</NoWarn>"]
    if args.lang:
        lines.append(f"    <LangVersion>{args.lang}</LangVersion>")
    if args.offline:
        cache = os.environ.get("NUGET_PACKAGES") or str(Path.home() / ".nuget" / "packages")
        lines.append(f"    <RestoreSources>{cache}</RestoreSources>")
    elif args.sources:
        lines.append(f"    <RestoreSources>{args.sources}</RestoreSources>")
    lines.append("  </PropertyGroup>")
    if args.package:
        lines.append("  <ItemGroup>")
        for p in args.package:
            pid, _, ver = p.partition("@")
            lines.append(f'    <PackageReference Include="{pid}" Version="{ver}" />')
        lines.append("  </ItemGroup>")
    lines.append("</Project>")
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("files", nargs="*")
    ap.add_argument("-e", dest="inline", action="append", default=[])
    ap.add_argument("--package", action="append", default=[])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--sources")
    ap.add_argument("--tfm", default="net10.0")
    ap.add_argument("--no-nullable", action="store_true")
    ap.add_argument("--no-implicit-usings", action="store_true")
    ap.add_argument("--lang")
    ap.add_argument("--warnings", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    args = ap.parse_args(argv)
    if args.help or not (args.files or args.inline):
        print(__doc__)
        return 2
    if shutil.which("dotnet") is None:
        print("dotnet SDK not found on PATH", file=sys.stderr)
        return 2
    for p in args.package:
        if "@" not in p or not p.split("@", 1)[1]:
            print(f"--package needs ID@VERSION, got {p!r}", file=sys.stderr)
            return 2

    folder = Path(tempfile.mkdtemp(prefix="cs_snippet_"))
    try:
        (folder / "snippet.csproj").write_text(project_text(args), encoding="utf-8", newline="\n")
        n = 0
        for code in args.inline:
            n += 1
            (folder / f"Snippet{n}.cs").write_text(code + "\n", encoding="utf-8", newline="\n")
        for f in args.files:
            n += 1
            shutil.copyfile(f, folder / (f"Snippet{n}_" + Path(f).name))
        proc = subprocess.run(["dotnet", "build", "--nologo", "-v", "q", "-clp:NoSummary"], cwd=folder, capture_output=True, text=True, timeout=600)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        errors, warnings, restore = {}, {}, {}
        for raw in out.splitlines():
            line = raw.strip()
            m = DIAG.match(line)
            if m:
                key = (m["code"], Path(m["file"]).name, m["line"], m["col"], m["msg"])
                (errors if m["kind"] == "error" else warnings)[key] = True
                continue
            m = RESTORE_DIAG.match(line)
            if m and m["kind"] == "error":
                restore[(m["code"], m["msg"])] = True
        if restore and not errors:
            for code, msg in restore:
                print(f"{code} {msg}")
            print("restore failed")
            return 3
        for (code, f, ln, col, msg) in errors:
            print(f"{code} {f}({ln},{col}) {msg}")
        if args.warnings:
            for (code, f, ln, col, msg) in warnings:
                print(f"{code} {f}({ln},{col}) {msg} (warning)")
        if errors:
            print(f"build FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
            return 1
        print(f"build succeeded: 0 errors, {len(warnings)} warning(s)" + ("" if args.warnings or not warnings else " (use --warnings to list them)"))
        if args.run:
            r = subprocess.run(["dotnet", "run", "--no-build"], cwd=folder, capture_output=True, text=True, timeout=60)
            sys.stdout.write(r.stdout)
            if r.stderr.strip():
                sys.stderr.write(r.stderr)
            return 0 if r.returncode == 0 else r.returncode
        return 0
    finally:
        if args.keep:
            print(f"kept: {folder}")
        else:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
