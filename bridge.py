"""Only the offline codecs are imported from the older MOD toolkit."""
from pathlib import Path
import sys

CORE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "core"
if not CORE.is_dir():
    CORE = Path(__file__).resolve().parent.parent / "fantasy-gauntlet-mod-tools"
sys.path.insert(0, str(CORE))

from wf_mod_tool import AMF3Reader  # noqa: E402
from wf_dsl import encode_amf3  # noqa: E402
import wf_flatomo_preview_render as flatomo  # noqa: E402
from wf_assets import mp3_encode, mp3_decode, mp3_probe

__all__ = ["AMF3Reader", "encode_amf3", "flatomo"]
