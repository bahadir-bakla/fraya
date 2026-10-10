"""Pipecat adapter: put the contract guard between the LLM and TTS.

    pipeline = Pipeline([transport.input(), stt, user_agg, llm,
                         ContractGuardProcessor(contract), tts,
                         transport.output(), assistant_agg])

* ``TranscriptionFrame`` (user speech) -> escalation / injection rules.
* ``FunctionCallResultFrame`` whose function name is in ``event_tools`` and
  whose result is truthy -> a policy event (e.g. ``verify_identity`` ->
  ``identity_verified``), which unlocks gated topics.
* ``LLMTextFrame`` chunks are held back and released as safe ``LLMTextFrame``s;
  a blocked turn is replaced by the rule's fallback and the rest is dropped.
* A handoff calls ``on_handoff(target)`` so the bot can transfer the call.

Requires ``pipecat-ai`` (tested with 1.12). The core package does not.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pipecat.frames.frames import (
    Frame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .contract import Contract
from .guard import Decision, StreamGuard


class ContractGuardProcessor(FrameProcessor):
    def __init__(
        self,
        contract: Contract,
        *,
        event_tools: dict[str, str] | None = None,
        on_handoff: Callable[[str], Awaitable[None]] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.guard = StreamGuard(contract)
        self.event_tools = event_tools or {"verify_identity": "identity_verified"}
        self.on_handoff = on_handoff
        self._in_turn = False

    async def _emit(self, d: Decision, direction: FrameDirection) -> None:
        if d.release:
            await self.push_frame(LLMTextFrame(d.release), direction)
        if d.handoff and self.on_handoff:
            await self.on_handoff(d.handoff)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            await self._emit(self.guard.on_user(frame.text), direction)
            await self.push_frame(frame, direction)
        elif isinstance(frame, FunctionCallResultFrame):
            event = self.event_tools.get(frame.function_name)
            if event and frame.result and not getattr(frame, "error", None):
                self.guard.on_event(event)
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._in_turn = True
            await self.push_frame(frame, direction)
            await self._emit(self.guard.start_agent_turn(), direction)
        elif isinstance(frame, LLMTextFrame) and direction == FrameDirection.DOWNSTREAM:
            if not self._in_turn:
                self._in_turn = True
                await self._emit(self.guard.start_agent_turn(), direction)
            await self._emit(self.guard.on_agent_chunk(frame.text), direction)
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._in_turn:
                await self._emit(self.guard.end_agent_turn(), direction)
                self._in_turn = False
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)
