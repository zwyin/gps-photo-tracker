"""EF-04: Checkpoint manager for resume-after-interruption."""
import json
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_FILE = ".checkpoint.json"


class CheckpointManager:
    """Manages .checkpoint.json in output directory for resume support.

    Only used in COPY mode. PREVIEW has no writes; OVERWRITE is unsafe to resume.
    """

    @staticmethod
    def create(output_dir: Path, total_photos: int) -> None:
        data = {
            "version": 1,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_photos": total_photos,
            "completed": [],
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / CHECKPOINT_FILE).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8",
        )

    @staticmethod
    def load(output_dir: Path) -> set[str]:
        cp_file = output_dir / CHECKPOINT_FILE
        if not cp_file.exists():
            return set()
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        return set(data.get("completed", []))

    @staticmethod
    def mark(output_dir: Path, filename: str) -> None:
        cp_file = output_dir / CHECKPOINT_FILE
        if not cp_file.exists():
            return
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        data["completed"].append(filename)
        cp_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def complete(output_dir: Path) -> None:
        cp_file = output_dir / CHECKPOINT_FILE
        if cp_file.exists():
            cp_file.unlink()

    @staticmethod
    def is_interrupted(output_dir: Path) -> bool:
        return (output_dir / CHECKPOINT_FILE).exists()
