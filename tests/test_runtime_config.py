import xml.etree.ElementTree as ET
from pathlib import Path
import unittest

import distribution_sources


class RuntimeConfigTests(unittest.TestCase):
    def test_remote_zone_runtime_switch_is_bundled_for_the_frozen_exe(self):
        config = Path(__file__).resolve().parents[1] / "starpoint-runtime.config"
        root = ET.parse(config).getroot()
        switch = root.find("./runtime/loadFromRemoteSources")
        self.assertIsNotNone(switch)
        self.assertEqual(switch.attrib.get("enabled"), "true")
        self.assertIn("starpoint-runtime.config", distribution_sources.SOURCE_FILES)
        self.assertIn("星点角色工坊.exe.config", Path(__file__).resolve().parents[1].joinpath("build_distribution.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
