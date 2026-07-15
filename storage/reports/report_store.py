import os
import json
import time
from typing import Any


class ReportStore:

    def __init__(self):

        self.path = "storage/reports"

        os.makedirs(self.path, exist_ok=True)

    def save_report(self, report: dict[str, Any], name: str = "report") -> str:

        filename = f"{name}_{int(time.time())}.json"

        full_path = os.path.join(self.path, filename)

        with open(full_path, "w") as f:

            json.dump(report, f, indent=2)

        return full_path
