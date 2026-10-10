import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.tests.utils import run_test

from voice_contract import load_contract
from voice_contract.pipecat_guard import ContractGuardProcessor

from .test_voice_contract import CARD, POLICY


def _llm_reply(text, size=4):
    return [LLMFullResponseStartFrame(), *[LLMTextFrame(text[i : i + size]) for i in range(0, len(text), size)], LLMFullResponseEndFrame()]


def _spoken(frames):
    return "".join(f.text for f in frames if isinstance(f, LLMTextFrame))


async def test_guard_in_pipeline_blocks_until_verified_then_releases():
    proc = ContractGuardProcessor(load_contract(POLICY))
    down, _ = await run_test(
        proc,
        frames_to_send=[
            *_llm_reply("Merhaba, Ayşe Hanım?"),
            TranscriptionFrame("Evet, borcum ne kadar?", "u1", "2026-10-08T00:00:00Z"),
            *_llm_reply("Borcunuz 3.200 TL görünüyor."),
            FunctionCallResultFrame(function_name="verify_identity", tool_call_id="t1", arguments={}, result={"ok": True}),
            *_llm_reply("Borcunuz 3.200 TL görünüyor."),
            *_llm_reply(f"Kartınız {CARD} değil mi?"),
        ],
    )
    spoken = _spoken(down)
    assert spoken.startswith("Bu görüşme kalite ve güvenlik amacıyla kayıt altına")
    first = spoken.split("3.200 TL")[0]
    assert "kimliğinizi doğrulamam gerekiyor" in first
    assert spoken.count("3.200 TL") == 1
    assert "4111" not in spoken and "Güvenliğiniz için" in spoken
    assert [v.rule_id for v in proc.guard.violations] == ["VC-02", "VC-03"]


async def test_handoff_callback_fires():
    targets = []

    async def on_handoff(t):
        targets.append(t)

    proc = ContractGuardProcessor(load_contract(POLICY), on_handoff=on_handoff)
    down, _ = await run_test(
        proc,
        frames_to_send=[
            TranscriptionFrame("Avukatım sizi arayacak.", "u1", "2026-10-08T00:00:00Z"),
            *_llm_reply("Peki, borcunuzu konuşalım."),
        ],
    )
    assert targets == ["human_agent"]
    assert "borcunuzu" not in _spoken(down)
