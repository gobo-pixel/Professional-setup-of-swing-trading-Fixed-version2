import json
import time
import os


class SnapshotManager:

    def save(self, state: dict):

        os.makedirs("storage/snapshots", exist_ok=True)

        filename = f"storage/snapshots/snap_{int(time.time())}.json"

        with open(filename, "w") as f:

            json.dump(state, f, indent=2)
