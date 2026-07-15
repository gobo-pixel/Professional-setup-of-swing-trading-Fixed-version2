import os
import json
from typing import Any


class ModelStore:

    def __init__(self):

        self.path = "storage/models"

        os.makedirs(self.path, exist_ok=True)

    def save_model(self, name: str, model: dict[str, Any]) -> str:

        file_path = os.path.join(self.path, f"{name}.json")

        with open(file_path, "w") as f:

            json.dump(model, f, indent=2)

        return file_path

    def load_model(self, name: str) -> dict[str, Any] | None:

        file_path = os.path.join(self.path, f"{name}.json")

        if not os.path.exists(file_path):

            return None

        with open(file_path, "r") as f:

            return json.load(f)
