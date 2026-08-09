import unittest
from unittest.mock import MagicMock, patch

from telegram_media_downloader.drive_ownership import (
    _transfer_one,
    list_remote_tree,
    remote_name,
    replace_remote_name,
)


class DriveOwnershipTests(unittest.TestCase):
    def test_replaces_only_rclone_config_name_and_preserves_options(self):
        original = "gdrive,root_folder_id=folder-id-:/Course"
        self.assertEqual(remote_name(original), "gdrive")
        self.assertEqual(
            replace_remote_name(original, "helper2"),
            "helper2,root_folder_id=folder-id-:/Course",
        )

    def test_consumer_transfer_is_accepted_by_target_owner(self):
        source = MagicMock()
        owner = MagicMock()
        owner.owner_emails.side_effect = [set(), {"owner@example.com"}]
        source.request.return_value = {"id": "owner-permission", "pendingOwner": True}

        changed = _transfer_one(
            source, owner, "file-id", "owner@example.com", "owner-permission",
        )

        self.assertTrue(changed)
        source.request.assert_called_once()
        method, path = owner.request.call_args.args
        self.assertEqual(method, "PATCH")
        self.assertIn("owner-permission", path)
        self.assertEqual(owner.request.call_args.kwargs["params"]["transferOwnership"], "true")

    def test_already_owned_file_is_idempotent(self):
        source = MagicMock()
        owner = MagicMock()
        owner.owner_emails.return_value = {"owner@example.com"}
        self.assertFalse(
            _transfer_one(source, owner, "file-id", "owner@example.com", "permission-id")
        )
        source.request.assert_not_called()

    @patch("telegram_media_downloader.drive_ownership._run_json")
    def test_remote_tree_resolves_course_folder_id_from_parent(self, run_json):
        run_json.side_effect = [
            [{"ID": "file-id", "Path": "video.mp4", "IsDir": False}],
            [{"ID": "folder-id", "Name": "Course", "Path": "Course", "IsDir": True}],
        ]
        items = list_remote_tree("helper,root_folder_id=parent-id-:/Course")
        self.assertEqual({item.file_id for item in items}, {"file-id", "folder-id"})
        self.assertEqual(items[-1].file_id, "folder-id")
        self.assertEqual(
            run_json.call_args_list[1].args[0],
            ["rclone", "lsjson", "helper,root_folder_id=parent-id-:", "--dirs-only"],
        )


if __name__ == "__main__":
    unittest.main()
