"""Interpreter selection must retain the configured virtual environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic_assist


class SemanticPythonVenvTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Regression exercises POSIX venv symlinks')
    def test_isolated_child_uses_explicit_or_environment_venv(self):
        with tempfile.TemporaryDirectory() as root:
            environment = Path(root) / 'semantic-venv'
            venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
            executable = environment / 'bin' / 'python'
            self.assertTrue(executable.is_symlink())
            for selection in ('explicit', 'environment'):
                with self.subTest(selection=selection):
                    # Exercise relative paths too; the returned path must be
                    # absolute without following the executable's symlink.
                    relative = os.path.relpath(executable)
                    configured = relative if selection == 'environment' else '/unused/python'
                    with patch.dict(os.environ, {'MINILM_PYTHON': configured}):
                        selected = semantic_assist.python_executable(
                            relative if selection == 'explicit' else None)
                    self.assertTrue(Path(selected).is_absolute())
                    result = subprocess.run(
                        [selected, '-I', '-c',
                         'import json, sys; print(json.dumps([sys.prefix, sys.base_prefix]))'],
                        check=True, capture_output=True, text=True, timeout=15,
                        env=semantic_assist.child_env(os.environ))
                    prefix, base_prefix = json.loads(result.stdout)
                    self.assertEqual(Path(prefix), environment)
                    self.assertNotEqual(prefix, base_prefix)


if __name__ == '__main__':
    unittest.main()
