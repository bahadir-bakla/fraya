"""Redact scoped service keys from inherited OASIS subprocess logging."""
import os

from authenticated_runtime import install_redaction

install_redaction([os.environ.get("LLM_API_KEY"), os.environ.get("ZEP_API_KEY")])
