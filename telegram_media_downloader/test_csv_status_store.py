import multiprocessing
import tempfile
import unittest
from pathlib import Path

from csv_status_store import claim_status, load_status, reset_transient_statuses


def normalize(value: str) -> str:
    return value.strip()


def claim_worker(csv_name: str, owner: str, start, results) -> None:
    start.wait()
    claimed, previous = claim_status(
        Path(csv_name), "same-course", owner, {"PENDING"}, normalize
    )
    results.put((owner, claimed, previous))


class CsvStatusStoreTests(unittest.TestCase):
    def test_only_one_process_can_claim_a_course(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "status.csv"
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            results = context.Queue()
            owners = ["PROCESSING_ACC1", "PROCESSING_ACC2", "PROCESSING_ACC3"]
            processes = [
                context.Process(
                    target=claim_worker,
                    args=(str(csv_path), owner, start, results),
                )
                for owner in owners
            ]

            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(15)
                self.assertEqual(process.exitcode, 0)

            outcomes = [results.get(timeout=2) for _ in owners]
            winners = [owner for owner, claimed, _ in outcomes if claimed]
            self.assertEqual(len(winners), 1)
            self.assertEqual(load_status(csv_path, normalize)["same-course"], winners[0])

    def test_clean_start_releases_transient_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "status.csv"
            claim_status(csv_path, "course-a", "PROCESSING_ACC1", {"PENDING"}, normalize)
            claim_status(csv_path, "course-b", "FORWARDED_ACC2", {"PENDING"}, normalize)

            self.assertEqual(reset_transient_statuses(csv_path), 2)
            statuses = load_status(csv_path, normalize)
            self.assertEqual(statuses["course-a"], "PENDING")
            self.assertEqual(statuses["course-b"], "PENDING")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
