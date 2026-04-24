from pathlib import Path

_AMBIENT_DIR = Path(__file__).parent.parent / "data" / "audio" / "ambient"


def _match_location(location_type: str) -> str:
    return "city_night.wav"


class AmbientManager:
    def __init__(self, ambient_dir: Path = _AMBIENT_DIR) -> None:
        self._dir = ambient_dir

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def set_location(self, location_type: str) -> None:
        pass
