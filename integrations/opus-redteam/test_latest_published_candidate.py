"""Offline candidate selection fixtures; no model, credentials or hosted calls."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run


OLDER = "2026-10-10T09:00:00+00:00"
LATEST = "2026-10-10T10:00:00+00:00"
NEWER = "2026-10-10T11:00:00+00:00"


def workflow():
    return {"initial_node": "welcome", "nodes": {
        "welcome": {"type": "conversation", "prompt": "Synthetic welcome"}}}


class LatestPublishedCandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="opus-candidate-test-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name).resolve()
        self.root = self.temporary / "fraya"
        self.root.mkdir()

    def write_json(self, path, value, encoding="utf-8"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding=encoding)

    def make_run(self, name, *, root=None, started=LATEST, phase="completed",
                 workflow_id="synthetic-published-workflow", value=None):
        root = self.root if root is None else root
        directory = root / "competition" / "runs" / name
        artifact = directory / "workflow.json"
        self.write_json(artifact, workflow() if value is None else value)
        status_path = directory / "status.json"
        self.write_json(status_path, {
            "phase": phase, "started": started,
            "freya": {"workflow_id": workflow_id},
            "artifacts": {"workflow": "workflow.json"},
        })
        return status_path, artifact.resolve()

    def assert_status_ignored(self, statuses):
        for index, (label, status) in enumerate(statuses):
            with self.subTest(status=label):
                root = self.root / str(index)
                _, expected = self.make_run("valid", root=root, started=OLDER)
                status_path, _ = self.make_run("invalid", root=root, started=NEWER)
                self.write_json(status_path, status)
                self.assertEqual(run.latest_published_candidate(root), expected)

    def test_latest_completed_published_artifact_wins_over_newer_inflight(self):
        self.make_run("z-older-completed", started=OLDER)
        _, expected = self.make_run("a-latest-completed", started=LATEST)
        self.make_run("zz-newer-inflight", started=NEWER, phase="generating")
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_started_time_wins_over_directory_name_and_file_mtime(self):
        old_status, old_artifact = self.make_run("z-last-by-name", started=OLDER)
        new_status, expected = self.make_run("a-first-by-name", started=LATEST)
        for path in (old_status, old_artifact):
            os.utime(path, (2000, 2000))
        for path in (new_status, expected):
            os.utime(path, (1000, 1000))
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_noncompleted_phases_are_ignored_even_with_published_workflow(self):
        _, expected = self.make_run("valid", started=OLDER)
        for index, phase in enumerate(("pending", "generating", "publishing", "failed", None)):
            with self.subTest(phase=phase):
                self.make_run(f"inflight-{index}", started=NEWER, phase=phase)
                self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_completed_but_unpublished_runs_are_ignored(self):
        _, expected = self.make_run("valid", started=OLDER)
        for index, workflow_id in enumerate((None, "", False)):
            with self.subTest(workflow_id=workflow_id):
                self.make_run(f"unpublished-{index}", started=NEWER, workflow_id=workflow_id)
                self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_missing_status_does_not_publish_existing_workflow(self):
        _, expected = self.make_run("valid", started=OLDER)
        self.write_json(self.root / "competition/runs/no-status/workflow.json", workflow())
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_malformed_status_json_is_skipped(self):
        _, expected = self.make_run("valid", started=OLDER)
        for index, text in enumerate(("", "{", '{"phase": "completed",')):
            with self.subTest(text=text):
                status_path, _ = self.make_run(f"malformed-{index}", started=NEWER)
                status_path.write_text(text, encoding="utf-8")
                self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_missing_or_malformed_status_fields_are_skipped(self):
        valid = {"phase": "completed", "started": NEWER,
                 "freya": {"workflow_id": "synthetic-published-workflow"},
                 "artifacts": {"workflow": "workflow.json"}}
        statuses = [("null", None), ("list", []), ("string", "completed"), ("empty", {})]
        for field in ("phase", "started", "freya", "artifacts"):
            status = deepcopy(valid)
            del status[field]
            statuses.append((f"missing-{field}", status))
        for field, values in (
            ("freya", (None, [], "published", {})),
            ("artifacts", (None, [], "workflow.json", {})),
        ):
            for index, value in enumerate(values):
                status = deepcopy(valid)
                status[field] = value
                statuses.append((f"{field}-{index}", status))
        for index, path in enumerate((None, [], {}, 42, "")):
            status = deepcopy(valid)
            status["artifacts"]["workflow"] = path
            statuses.append((f"workflow-path-{index}", status))
        self.assert_status_ignored(statuses)

    def test_missing_workflow_file_is_skipped(self):
        _, expected = self.make_run("valid", started=OLDER)
        status_path, _ = self.make_run("missing-workflow", started=NEWER)
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["artifacts"]["workflow"] = "does-not-exist.json"
        self.write_json(status_path, status)
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_workflow_directory_is_not_an_artifact(self):
        _, expected = self.make_run("valid", started=OLDER)
        status_path, _ = self.make_run("directory-workflow", started=NEWER)
        (status_path.parent / "artifact-directory").mkdir()
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["artifacts"]["workflow"] = "artifact-directory"
        self.write_json(status_path, status)
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_malformed_workflow_json_is_skipped(self):
        _, expected = self.make_run("valid", started=OLDER)
        for index, text in enumerate(("", "{", '{"nodes":')):
            with self.subTest(text=text):
                _, artifact = self.make_run(f"malformed-workflow-{index}", started=NEWER)
                artifact.write_text(text, encoding="utf-8")
                self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_malformed_workflow_shapes_are_skipped(self):
        values = ([], "workflow", 42, {}, {"workflow": None}, {"workflow": []},
                  {"initial_node": "welcome", "nodes": []},
                  {"initial_node": "welcome", "nodes": None})
        for index, value in enumerate(values):
            with self.subTest(workflow=value):
                root = self.root / str(index)
                _, expected = self.make_run("valid", root=root, started=OLDER)
                self.make_run("invalid", root=root, started=NEWER, value=value)
                self.assertEqual(run.latest_published_candidate(root), expected)
        root = self.root / "null"
        _, expected = self.make_run("valid", root=root, started=OLDER)
        _, artifact = self.make_run("invalid", root=root, started=NEWER)
        self.write_json(artifact, None)
        self.assertEqual(run.latest_published_candidate(root), expected)

    def test_missing_or_invalid_initial_node_is_skipped(self):
        values = ({"nodes": workflow()["nodes"]},
                  {"initial_node": "absent", "nodes": workflow()["nodes"]},
                  {"initial_node": None, "nodes": workflow()["nodes"]},
                  {"initial_node": [], "nodes": workflow()["nodes"]},
                  {"initial_node": {}, "nodes": workflow()["nodes"]},
                  {"initial_node": "welcome", "nodes": {}})
        for index, value in enumerate(values):
            with self.subTest(workflow=value):
                root = self.root / str(index)
                _, expected = self.make_run("valid", root=root, started=OLDER)
                self.make_run("invalid", root=root, started=NEWER, value=value)
                self.assertEqual(run.latest_published_candidate(root), expected)

    def test_wrapped_workflow_and_utf8_bom_are_accepted(self):
        status_path, expected = self.make_run("wrapped")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        self.write_json(status_path, status, encoding="utf-8-sig")
        self.write_json(expected, {"workflow": workflow()}, encoding="utf-8-sig")
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def assert_escape_rejected(self, absolute):
        _, expected = self.make_run("valid", started=OLDER)
        status_path, _ = self.make_run("escape", started=NEWER)
        # A sibling sharing the root's prefix catches string-prefix containment checks.
        outside = self.temporary / "fraya-sibling" / "workflow.json"
        self.write_json(outside, workflow())
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["artifacts"]["workflow"] = (
            str(outside) if absolute else os.path.relpath(outside, status_path.parent))
        self.write_json(status_path, status)
        original_read_text = Path.read_text

        def guarded_read_text(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), outside.resolve(),
                                "Escaped artifacts must be rejected before reading")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded_read_text):
            self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_relative_path_escape_is_rejected_before_reading(self):
        self.assert_escape_rejected(absolute=False)

    def test_absolute_path_outside_root_is_rejected_before_reading(self):
        self.assert_escape_rejected(absolute=True)

    def test_absolute_path_inside_root_is_accepted(self):
        status_path, expected = self.make_run("absolute-inside")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["artifacts"]["workflow"] = str(expected)
        self.write_json(status_path, status)
        self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_only_the_artifact_named_in_status_is_considered(self):
        status_path, _ = self.make_run("explicit-artifact")
        expected = status_path.parent / "published" / "workflow-final.json"
        self.write_json(expected, {"workflow": workflow()})
        (status_path.parent / "workflow.json").write_text("{", encoding="utf-8")
        self.write_json(status_path.parent / "workflow-newer.json", workflow())
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["artifacts"]["workflow"] = "published/workflow-final.json"
        self.write_json(status_path, status)
        self.assertEqual(run.latest_published_candidate(self.root), expected.resolve())

    def test_unreadable_status_or_workflow_does_not_hide_valid_candidate(self):
        _, expected = self.make_run("valid", started=OLDER)
        status_path, artifact = self.make_run("unreadable", started=NEWER)
        original_read_text = Path.read_text
        for blocked_path in (status_path, artifact):
            with self.subTest(unreadable=blocked_path.name):
                def guarded_read_text(path, *args, **kwargs):
                    if path == blocked_path:
                        raise PermissionError("Synthetic unreadable fixture")
                    return original_read_text(path, *args, **kwargs)

                with patch.object(Path, "read_text", guarded_read_text):
                    self.assertEqual(run.latest_published_candidate(self.root), expected)

    def test_malformed_started_types_do_not_break_status_selection(self):
        statuses = []
        for value in (None, 42, False, [], {}):
            statuses.append((type(value).__name__, {
                "phase": "completed", "started": value,
                "freya": {"workflow_id": "synthetic-published-workflow"},
                "artifacts": {"workflow": "workflow.json"},
            }))
        self.assert_status_ignored(statuses)

    def test_no_runs_returns_none(self):
        self.assertIsNone(run.latest_published_candidate(self.root))

    def test_empty_runs_directory_returns_none(self):
        (self.root / "competition/runs").mkdir(parents=True)
        self.assertIsNone(run.latest_published_candidate(self.root))

    def test_no_completed_published_valid_artifact_returns_none(self):
        self.make_run("inflight", phase="generating")
        self.make_run("unpublished", workflow_id=None)
        self.make_run("invalid", value={"initial_node": "missing", "nodes": {}})
        status_path, _ = self.make_run("missing")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["artifacts"]["workflow"] = "missing.json"
        self.write_json(status_path, status)
        self.assertIsNone(run.latest_published_candidate(self.root))


if __name__ == "__main__":
    unittest.main()
