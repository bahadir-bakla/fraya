import unittest
from builder import model_permissions


class ModelPermissionTests(unittest.TestCase):
    def test_no_inherited_access_defaults_to_workspace(self):
        self.assertEqual(model_permissions({}), ':workspace')

    def test_read_only_parent_cannot_be_widened(self):
        self.assertEqual(model_permissions({'CODEX_PERMISSION_PROFILE': ':read-only'}), ':read-only')

    def test_explicit_full_access_parent_is_preserved(self):
        self.assertEqual(model_permissions({'CODEX_PERMISSION_PROFILE': ':danger-full-access'}), ':danger-full-access')

    def test_cli_configuration_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            model_permissions({'CODEX_PERMISSION_PROFILE': ':workspace\napproval_policy=on-request'})
