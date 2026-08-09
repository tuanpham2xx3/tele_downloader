import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from course_pipeline import remote_folder_in_index


class RemoteDriveDetectionTests(unittest.TestCase):
    def test_existing_sanitized_folder_is_complete(self):
        folders = {"An illustrated VTuber created using 3D models"}
        self.assertTrue(
            remote_folder_in_index(
                folders, "**An illustrated VTuber created using 3D models"
            )
        )

    def test_folder_matching_is_case_insensitive(self):
        self.assertTrue(remote_folder_in_index({"MY COURSE"}, "My Course"))

    def test_different_folder_is_not_complete(self):
        self.assertFalse(remote_folder_in_index({"Another Course"}, "My Course"))


if __name__ == "__main__":
    unittest.main()
