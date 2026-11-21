"""Parse files straight from disk without touching the database (corpus triage)."""
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

from assessments.extraction.pipeline import analyze


class Command(BaseCommand):
    help = "Run the extractor over files or directories and print one line per file."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+")
        parser.add_argument("--verbose", action="store_true", help="print components too")

    def handle(self, *args, **options):
        paths: list[Path] = []
        for raw in options["paths"]:
            path = Path(raw)
            if path.is_dir():
                paths.extend(sorted(
                    p for p in path.rglob("*")
                    if p.suffix.lower() in {".pdf", ".docx", ".xlsx"} and p.is_file()
                ))
            elif path.is_file():
                paths.append(path)
            else:
                self.stderr.write(f"skip (not found): {path}")
        counts: dict[str, int] = {}
        for path in paths:
            result = analyze(str(path))
            status = result["status"]
            counts[status] = counts.get(status, 0) + 1
            top = result["components"]
            self.stdout.write(
                f"{status:12} {result.get('fingerprint', ''):12} "
                f"{len(top):2} items {sum(c['weight'] or 0 for c in top):6.2f}%  {path.name}"
            )
            if options["verbose"]:
                for component in top:
                    self.stdout.write(f"    {component['weight']!s:>6}  {component['name']}")
                for reason in result["reasons"]:
                    self.stdout.write(f"    · {reason}")
        summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        self.stdout.write(self.style.SUCCESS(f"{len(paths)} file(s): {summary}"))
        if not paths:
            sys.exit(1)
