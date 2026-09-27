"""Build a patched Freerouting jar: the 2.4.1 jar with the classes named by the patches in `tools/` recompiled from
the 2.4.1 source. D107 (`freerouting-2.4.1-d107.patch`): per-layer trace costs handed over in the DSN's
autoroute_settings block survive `RouterSettings.applyBoardSpecificOptimizations`. D109 (`-d109.patch`): the
shove's recursion depths in `AutorouteControl` doubled.

    python3 scripts/patch_freerouting.py [<freerouting checkout with the v2.4.1 tag>] [d107 d109 ...]

Needs the fetched JDK and jar (`scripts/fetch_tools.py`) and a checkout of freerouting that has the `v2.4.1` tag
(the owner's fork at /home/user/thuddwhirr/freerouting after `git fetch --depth 1 <upstream> tag v2.4.1`).
Writes build/tools/freerouting-2.4.1-<names>.jar (every patch in `tools/` when none is named); run the router
with it through `WAFFLE_FREEROUTING_JAR`."""
import subprocess
import sys
import tempfile
from pathlib import Path

import _path  # noqa
from waffle_eda.route import freerouting as fr

def patched_source(patch: Path) -> str:
    """The source file a patch changes, from its `+++ b/...` header."""
    for line in patch.read_text().splitlines():
        if line.startswith("+++ b/"):
            return line[len("+++ b/"):].strip()
    raise ValueError(f"{patch}: no +++ b/ header")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    checkout = Path(args.pop(0)) if args and Path(args[0]).is_dir() else Path("/home/user/thuddwhirr/freerouting")
    tools = Path(__file__).resolve().parents[1] / "tools"
    patches = ([tools / f"freerouting-2.4.1-{name}.patch" for name in args] if args
               else sorted(tools.glob("freerouting-2.4.1-*.patch")))
    names = "-".join(p.stem.split("-")[-1] for p in patches)
    jar, jdk = fr.jar_path(), fr.java_path().parent
    out = jar.with_name(f"freerouting-2.4.1-{names}.jar")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        sources = []
        for patch in patches:
            source = patched_source(patch)
            src = work / "src" / source
            src.parent.mkdir(parents=True, exist_ok=True)
            if not src.exists():
                src.write_text(subprocess.run(["git", "-C", str(checkout), "show", f"v2.4.1:{source}"], check=True,
                                              capture_output=True, text=True).stdout)
            subprocess.run(["patch", "-p1", "-d", str(work / "src"), "-i", str(patch)], check=True)
            sources.append(str(src))
        classes = work / "classes"
        classes.mkdir()
        subprocess.run([str(jdk / "javac"), "-nowarn", "-cp", str(jar), "-d", str(classes)] + sources, check=True)
        out.write_bytes(jar.read_bytes())
        built = sorted(p.relative_to(classes) for p in classes.rglob("*.class"))
        subprocess.run([str(jdk / "jar"), "uf", str(out)] + [str(p) for p in built], cwd=classes, check=True)
        print(f"{out}: {len(built)} classes replaced: {[str(p) for p in built]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
