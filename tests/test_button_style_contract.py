import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ButtonStyleContractTests(unittest.TestCase):
    def test_global_button_rule_forces_sharp_corners(self):
        stylesheet = (ROOT / "style.css").read_text(encoding="utf-8")
        stylesheet = re.sub(r"/\*.*?\*/", "", stylesheet, flags=re.DOTALL)
        button_rules = [
            declarations
            for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", stylesheet)
            if "button" in {selector.strip() for selector in selectors.split(",")}
        ]

        self.assertTrue(
            any(
                re.search(r"border-radius\s*:\s*0(?:px)?\s*!important", declarations)
                for declarations in button_rules
            ),
            "Every button must resolve to sharp corners, including more-specific legacy button classes.",
        )


if __name__ == "__main__":
    unittest.main()
