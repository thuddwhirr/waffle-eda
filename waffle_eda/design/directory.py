"""The design directory (`docs/plan.md`, "Interface"): where each stage's files are, and what a design waits on."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from waffle_eda.design import gate

STAGES = ((1, "design"), (2, "bom"), (3, "schematic"), (4, "spec"), (5, "layout"), (6, "outputs"))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def designs_dir() -> Path:
    return repo_root() / "designs"


@dataclass(frozen=True)
class Design:
    name: str
    root: Path

    @classmethod
    def named(cls, name: str) -> "Design":
        return cls(name, designs_dir() / name)

    # stage files, as the plan's "Interface" section lists them
    @property
    def design_md(self) -> Path:
        return self.root / "design.md"

    @property
    def bom_csv(self) -> Path:
        return self.root / "bom.csv"

    @property
    def kicad_dir(self) -> Path:
        """One KiCad project holds the schematic (stage 3) and the board (stage 5), as KiCad expects them."""
        return self.root / "kicad"

    @property
    def schematic(self) -> Path:
        return self.kicad_dir / f"{self.name}.kicad_sch"

    @property
    def project(self) -> Path:
        return self.kicad_dir / f"{self.name}.kicad_pro"

    @property
    def netlist(self) -> Path:
        return self.root / "netlist.net"

    @property
    def spec_toml(self) -> Path:
        return self.root / "spec.toml"

    @property
    def board(self) -> Path:
        return self.kicad_dir / f"{self.name}.kicad_pcb"

    @property
    def rules(self) -> Path:
        return self.kicad_dir / f"{self.name}.kicad_dru"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def work(self) -> Path:
        """Scratch that is not part of the design: the router's files, DRC copies (under build/, ignored)."""
        return repo_root() / "build" / "designs" / self.name

    def relative(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.root.resolve()))
        except ValueError:
            return str(path)

    def result(self, stage: int) -> gate.GateResult | None:
        name = dict(STAGES)[stage]
        return gate.read_report(self.reports, stage, name)

    def status(self) -> str:
        """Where the design is: each stage's gate, and what it waits on from the owner."""
        lines = [f"design {self.name} ({self.root})"]
        waiting: list[str] = []
        stopped = False
        for stage, name in STAGES:
            r = self.result(stage)
            if r is None:
                lines.append(f"  stage {stage} {name:<10} not run" + ("" if stopped else ""))
                if not stopped:
                    stopped = True
                continue
            state = "PASS" if r.passed else "FAIL"
            lines.append(f"  stage {stage} {name:<10} {state}  ({r.when}; {len(r.checks)} criteria, "
                         f"{len(r.failing)} failing, {len(r.escalated)} waiting on the owner)")
            for c in r.failing:
                lines.append(f"      FAIL {c.criterion}: {c.detail}")
            waiting += [f"stage {stage}: {c.criterion}: {c.detail}" for c in r.escalated]
            if not r.passed:
                stopped = True
        first_not_run = next((s for s, _n in STAGES if self.result(s) is None), None)
        failed = next((s for s, _n in STAGES if self.result(s) is not None and not self.result(s).passed), None)
        if failed:
            lines.append(f"  at the gate of stage {failed}: failed; see reports/stage{failed}-{dict(STAGES)[failed]}.md")
        elif first_not_run:
            lines.append(f"  at the gate of stage {first_not_run - 1 if first_not_run > 1 else 1}: next is stage {first_not_run}")
        else:
            lines.append("  through every gate: fab outputs under out/, for the owner's review")
        if waiting:
            lines.append("  waiting on the owner:")
            lines += [f"    - {w}" for w in waiting]
        else:
            lines.append("  waiting on the owner: nothing")
        return "\n".join(lines)
