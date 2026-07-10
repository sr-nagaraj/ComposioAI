"""Checkpoint persistence placeholder."""

from pathlib import Path


class CheckpointManager:
    """Track stage progress for resumable runs."""

    def __init__(self, checkpoint_path: Path) -> None:
        self.checkpoint_path = checkpoint_path

    async def load(self) -> dict[str, object]:
        raise NotImplementedError("Checkpoint persistence is planned for a later phase.")

    async def save(self, checkpoint: dict[str, object]) -> None:
        raise NotImplementedError("Checkpoint persistence is planned for a later phase.")
