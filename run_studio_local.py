"""Run Falcon Studio on Windows with the locally downloaded weights.

The upstream server resolves weights through Hugging Face; this wrapper points
Engine at weights/falcon.pt or weights/falcon-big.pt instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROBE = Path(__file__).resolve().parent
STUDIO = PROBE / "Falcon" / "studio"
sys.path.insert(0, str(STUDIO))

import server  # noqa: E402
from falcon_runtime import FalconRuntime  # noqa: E402


def _load(self):
    try:
        weights = PROBE / "weights" / ("falcon-big.pt" if self.variant == "big" else "falcon.pt")
        runtime = FalconRuntime(variant=self.variant, checkpoint_path=str(weights))
        runtime.load(device=self.device)
        self.runtime = runtime
    except Exception as exc:
        server.log.exception("Falcon initialization failed")
        self.error = str(exc)
    finally:
        self.loading = False


server.Engine._load = _load

if __name__ == "__main__":
    server.main()
