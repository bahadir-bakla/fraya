"""Lazily construct one ephemeral Modal function; importing this file is offline.

Only the three named adapter files and public model manifest enter the image.
No auto source discovery, local-directory upload, volume, secret, or service.
"""
from pathlib import Path

REMOTE_FILES = ("modal_narrow_core.py", "modal_narrow_teacher.py", "modal_narrow_model.json", "modal_narrow_app.py")
PINS = ("torch==2.11.0", "transformers==5.3.0", "safetensors==0.8.0rc0", "huggingface-hub==1.7.1")


def remote_job(payload_blob, expected_sha, manifest, compute_seconds, stop_epoch):
    # Imports resolve only from the three explicit image files below.
    import sys
    sys.path.insert(0, "/opt/narrow")
    from modal_narrow_teacher import run_teacher
    return run_teacher(payload_blob, expected_sha, manifest, "/tmp/public-e5", compute_seconds,
                       stop_epoch, device="cuda", download=True)


def create_app(compute_seconds=120, modal_module=None):
    if type(compute_seconds) is not int or not 1 <= compute_seconds <= 1800:
        raise ValueError("Bounded per-input timeout required")
    if modal_module is None:
        import modal as modal_module
    here = Path(__file__).resolve().parent
    image = modal_module.Image.debian_slim(python_version="3.11").pip_install(*PINS).env({"PYTHONPATH":"/opt/narrow", "HF_HUB_DISABLE_TELEMETRY":"1"})
    for name in REMOTE_FILES:
        image = image.add_local_file(str(here/name), remote_path="/opt/narrow/"+name)
    app = modal_module.App("learned-narrow-v3-ephemeral", include_source=False)
    function = app.function(image=image, serialized=True, include_source=False,
                            gpu="H100", cpu=(2, 2), memory=(16384, 16384), ephemeral_disk=2048,
                            retries=0, timeout=compute_seconds, startup_timeout=240,
                            min_containers=0, buffer_containers=0, max_containers=1,
                            scaledown_window=2, single_use_containers=True,
                            secrets=[], volumes={}, schedule=None)(remote_job)
    return app, function
