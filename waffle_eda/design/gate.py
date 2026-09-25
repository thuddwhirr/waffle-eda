"""What every stage returns: the gate's criteria as the definition states them, each checked, escalated or
failed, written as the stage's report (`docs/definition.md` section 2; CLAUDE.md, "Writing").

A criterion the tool cannot check (the price against a ceiling when no price is captured, the owner's review)
is *escalated*: it neither passes nor fails the gate, and the design waits on the owner for it. The report
opens with PASS or FAIL, lists the failing criteria first, then the escalations, the numbers and what is next.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Check:
    criterion: str
    ok: bool | None  # None: cannot be checked by the tool; escalated to the owner
    detail: str = ""


@dataclass
class GateResult:
    stage: int
    name: str
    checks: list[Check] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)  # files written, relative to the design directory
    numbers: dict = field(default_factory=dict)
    next: str = ""
    seconds: float = 0.0
    when: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))

    @property
    def passed(self) -> bool:
        return all(c.ok is not False for c in self.checks)

    @property
    def failing(self) -> list[Check]:
        return [c for c in self.checks if c.ok is False]

    @property
    def escalated(self) -> list[Check]:
        return [c for c in self.checks if c.ok is None]

    def fail(self, criterion: str, detail: str) -> None:
        self.checks.append(Check(criterion, False, detail))

    def ok(self, criterion: str, detail: str = "") -> None:
        self.checks.append(Check(criterion, True, detail))

    def escalate(self, criterion: str, detail: str) -> None:
        self.checks.append(Check(criterion, None, detail))

    def check(self, criterion: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(criterion, bool(ok), detail))
        return bool(ok)

    def report(self) -> str:
        lines = [f"# Stage {self.stage}, {self.name}: {'PASS' if self.passed else 'FAIL'}", "",
                 f"{self.when}, {self.seconds:.1f} s."]
        if self.failing:
            lines += ["", "## Failing", ""]
            lines += [f"- **{c.criterion}**: {c.detail}" for c in self.failing]
        if self.escalated:
            lines += ["", "## Waiting on the owner", ""]
            lines += [f"- **{c.criterion}**: {c.detail}" for c in self.escalated]
        passing = [c for c in self.checks if c.ok]
        if passing:
            lines += ["", "## Criteria met", ""]
            lines += [f"- {c.criterion}" + (f": {c.detail}" if c.detail else "") for c in passing]
        if self.numbers:
            lines += ["", "## Numbers", ""]
            lines += [f"- {k}: {v}" for k, v in self.numbers.items()]
        if self.outputs:
            lines += ["", "## Files", ""]
            lines += [f"- `{o}`" for o in self.outputs]
        if self.next:
            lines += ["", "## Next", "", self.next]
        return "\n".join(lines) + "\n"

    def to_json(self) -> dict:
        d = asdict(self)
        d["passed"] = self.passed
        return d

    @classmethod
    def from_json(cls, data: dict) -> "GateResult":
        data = dict(data)
        data.pop("passed", None)
        data["checks"] = [Check(**c) for c in data.get("checks", [])]
        return cls(**data)


def write_report(result: GateResult, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"stage{result.stage}-{result.name}"
    md, js = reports_dir / f"{stem}.md", reports_dir / f"{stem}.json"
    md.write_text(result.report())
    js.write_text(json.dumps(result.to_json(), indent=1))
    return md, js


def read_report(reports_dir: Path, stage: int, name: str) -> GateResult | None:
    js = reports_dir / f"stage{stage}-{name}.json"
    if not js.is_file():
        return None
    return GateResult.from_json(json.loads(js.read_text()))
