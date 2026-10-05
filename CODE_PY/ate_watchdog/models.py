from dataclasses import dataclass, field


@dataclass
class Finding:
    finding_id: str
    file_path: str
    line: int
    rule_id: str
    severity: str  # "high" | "medium" | "low"
    message: str
    suggested_fix: str = ""   # unified diff text, empty면 자동수정안 없음
    original_snippet: str = ""
    fixed_snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.finding_id,
            "file": self.file_path,
            "line": self.line,
            "rule": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "has_fix": bool(self.suggested_fix),
            "suggested_fix": self.suggested_fix,
            "original_snippet": self.original_snippet,
            "fixed_snippet": self.fixed_snippet,
        }

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        return Finding(
            finding_id=d["id"],
            file_path=d["file"],
            line=d["line"],
            rule_id=d["rule"],
            severity=d["severity"],
            message=d["message"],
            suggested_fix=d.get("suggested_fix", ""),
            original_snippet=d.get("original_snippet", ""),
            fixed_snippet=d.get("fixed_snippet", ""),
        )
