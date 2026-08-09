import tempfile
import unittest
from pathlib import Path

from telegram_media_downloader.upload_queue import (
    DOWNLOADED, PROCESSING, READY_UPLOAD, UPLOADING, UploadQueue,
)


class UploadQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = UploadQueue(Path(self.temp.name) / "jobs.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_enqueue_is_idempotent(self):
        args = dict(title="Course", normalized_title="course", owner="acc1",
                    course_dir=Path(self.temp.name) / "course", rclone_parent="gdrive:")
        first = self.queue.enqueue_downloaded(**args)
        second = self.queue.enqueue_downloaded(**{**args, "owner": "acc2"})
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.owner, "acc2")
        self.assertEqual(self.queue.pending_count(), 1)

    def test_claim_is_exclusive(self):
        self.queue.enqueue_downloaded(title="Course", normalized_title="course", owner="acc1",
                                      course_dir=self.temp.name, rclone_parent="gdrive:")
        first = self.queue.claim((DOWNLOADED,), PROCESSING)
        second = self.queue.claim((DOWNLOADED,), PROCESSING)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_recover_inflight(self):
        one = self.queue.enqueue_downloaded(title="One", normalized_title="one", owner="acc1",
                                            course_dir=self.temp.name, rclone_parent="gdrive:")
        two = self.queue.enqueue_downloaded(title="Two", normalized_title="two", owner="acc2",
                                            course_dir=self.temp.name, rclone_parent="gdrive:")
        self.queue.set_status(one.id, PROCESSING)
        self.queue.set_status(two.id, UPLOADING)
        self.assertEqual(self.queue.recover_inflight(), 2)
        self.assertEqual(self.queue.claim((DOWNLOADED,), PROCESSING).id, one.id)
        self.assertEqual(self.queue.claim((READY_UPLOAD,), UPLOADING).id, two.id)

    def test_lists_completed_jobs_for_cleanup_recovery(self):
        job = self.queue.enqueue_downloaded(title="Course", normalized_title="course", owner="acc1",
                                            course_dir=self.temp.name, rclone_parent="gdrive:")
        self.queue.set_status(job.id, "COMPLETED")
        self.assertEqual([item.id for item in self.queue.jobs_with_status("COMPLETED")], [job.id])


if __name__ == "__main__":
    unittest.main()
