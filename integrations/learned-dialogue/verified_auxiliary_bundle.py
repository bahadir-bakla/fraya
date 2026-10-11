"""Load hash-pinned diagnostic models without granting bank authority.

The caller supplies the trusted digest and taxonomy from a frozen experiment.
This validates serialized inference coefficients, not statistical accuracy or
the trustworthiness of customer input. It never downloads or executes a model.
"""
import hashlib
import json
import math
from pathlib import Path
import re

MAX_BYTES = 500_000


class BundleRejected(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise BundleRejected(reason)


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def _constant(_value):
    raise BundleRejected("Nonfinite JSON constant")


def _scalar(value, integer=False):
    if integer:
        _require(type(value) is int and -32767 <= value <= 32767,
                 "Invalid int16 coefficient")
    else:
        _require(type(value) in (int, float) and math.isfinite(value),
                 "Invalid numeric coefficient")


def _array(value, shape, integer=False):
    _require(type(value) is list and len(value) == shape[0],
             "Coefficient shape mismatch")
    for child in value:
        if len(shape) == 1:
            _scalar(child, integer)
        else:
            _array(child, shape[1:], integer)


def load_auxiliary(path, *, expected_sha256, expected_labels, kind):
    """Return a validated offline auxiliary bundle; no permission is returned."""
    _require(type(expected_sha256) is str and
             re.fullmatch(r"[0-9a-f]{64}", expected_sha256), "Trusted SHA256 required")
    with Path(path).open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    _require(len(data) <= MAX_BYTES, "Bundle exceeds portable size bound")
    _require(hashlib.sha256(data).hexdigest() == expected_sha256,
             "Bundle digest mismatch")
    try:
        model = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BundleRejected("Malformed model JSON") from error
    _require(type(model) is dict, "Model must be an object")
    _require(type(expected_labels) is list and len(expected_labels) == 77 and
             all(type(v) is str and v for v in expected_labels) and
             len(set(expected_labels)) == 77, "Trusted ordered taxonomy required")
    if kind == "public_intent_v2":
        _require(model.get("version") == "day2.public_source_intent.calibrated.v2",
                 "Unsupported model version")
        _require(model.get("qualified") is False and model.get("bank_mapping") is None,
                 "Auxiliary model cannot claim bank authority")
        _require(model.get("publisher_labels") == expected_labels, "Taxonomy mismatch")
        _require(type(model.get("use_edges")) is bool, "Typed edge flag required")
        parameters = model.get("parameters")
        _require(type(parameters) is dict, "Missing coefficients")
        if model.get("architecture") == "sparse_softmax":
            shapes = {"bias": (77,), "weight_scale": (77,), "weights_q": (512, 77)}
            quantized = {"weights_q"}
        else:
            _require(model.get("architecture") == "tiny_relational_gnn",
                     "Unsupported architecture")
            shapes = {"bias": (77,), "embedding": (512, 24),
                      "embedding_bias": (24,), "message_bias": (24,),
                      "readout": (24, 77), "self": (24, 24),
                      "source_order": (24, 24), "turn_membership": (24, 24)}
            quantized = set()
        _require(set(parameters) == set(shapes), "Unknown or missing coefficients")
        for field, shape in shapes.items():
            _array(parameters[field], shape, field in quantized)
        if "weight_scale" in parameters:
            _require(all(v > 0 for v in parameters["weight_scale"]),
                     "Quantization scale must be positive")
        calibration = model.get("calibration")
        _require(type(calibration) is dict and calibration.get("fitted") is True,
                 "Frozen calibration required")
        temperature, threshold = calibration.get("temperature"), calibration.get("threshold")
    elif kind == "minilm_offline_head":
        _require(type(model.get("schema_version")) is int and model["schema_version"] == 1,
                 "Unsupported head version")
        _require(model.get("task") == "banking77_publisher_support_intent_auxiliary" and
                 model.get("usage") == "offline_teacher_reference_only" and
                 model.get("bank_policy_target") is None and model.get("ledger_target") is None,
                 "Teacher cannot claim bank authority")
        _require(model.get("labels") == expected_labels, "Taxonomy mismatch")
        _require(type(model.get("embedding_width")) is int and model["embedding_width"] == 384,
                 "Encoder width mismatch")
        _array(model.get("weights_qint16"), (77, 384), True)
        _array(model.get("weight_scales"), (77,))
        _array(model.get("intercept"), (77,))
        _require(all(v > 0 for v in model["weight_scales"]), "Positive scales required")
        encoder = model.get("encoder")
        _require(type(encoder) is dict and encoder.get("trust_remote_code") is False and
                 encoder.get("local_files_only_inference") is True and
                 encoder.get("use_safetensors") is True, "Local safe encoder required")
        temperature, threshold = model.get("temperature"), model.get("threshold")
    else:
        raise BundleRejected("Unsupported model kind")
    _scalar(temperature)
    _scalar(threshold)
    _require(temperature > 0 and 0 <= threshold <= 1.1,
             "Invalid temperature or abstention threshold")
    return model
