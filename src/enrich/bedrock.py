"""Bedrock client wrapper.

Uses the Converse API rather than raw InvokeModel: one interface across model
families, and native tool-use support, so the response shape is constrained at
the API level instead of by asking politely for JSON.
"""

from __future__ import annotations

import logging
import os
import random
import time

from .prompt import SYSTEM, TOOL_SCHEMA, build_user_message

LOG = logging.getLogger(__name__)

# Model IDs expire. This is read from the environment and logged with every
# result rather than hardcoded - a retired ID hardcoded in source is a silent
# breakage waiting for the next release cycle.
DEFAULT_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# Per-million-token rates. Verify against current Bedrock pricing before
# quoting any cost figure - these move.
INPUT_COST_PER_MTOK = float(os.environ.get("BEDROCK_INPUT_COST", "1.00"))
OUTPUT_COST_PER_MTOK = float(os.environ.get("BEDROCK_OUTPUT_COST", "5.00"))

RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}


class BedrockError(RuntimeError):
    """Unrecoverable Bedrock failure."""


class NoToolUseError(BedrockError):
    """Model replied in prose instead of calling the tool."""


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
        + output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK
    )


class BedrockAssessor:
    def __init__(
        self,
        model_id: str | None = None,
        region: str = "us-east-1",
        client=None,
        max_retries: int = 4,
        base_delay: float = 1.0,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> None:
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_tokens = max_tokens
        # Zero temperature because this is a classification task being scored.
        # Sampling variance would show up in the eval as model quality.
        self.temperature = temperature
        self._client = client
        self._region = region

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def assess(self, record: dict) -> dict:
        """Call the model once. Returns the raw tool input plus usage metadata."""
        from botocore.exceptions import ClientError

        message = {"role": "user", "content": [{"text": build_user_message(record)}]}

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            started = time.monotonic()
            try:
                response = self.client.converse(
                    modelId=self.model_id,
                    system=[{"text": SYSTEM}],
                    messages=[message],
                    toolConfig={
                        "tools": [{"toolSpec": TOOL_SCHEMA}],
                        # Force the tool call. Without this the model may answer
                        # in prose and the response has no parseable structure.
                        "toolChoice": {"tool": {"name": TOOL_SCHEMA["name"]}},
                    },
                    inferenceConfig={
                        "maxTokens": self.max_tokens,
                        "temperature": self.temperature,
                    },
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in RETRYABLE and attempt < self.max_retries - 1:
                    delay = random.uniform(0, min(30.0, self.base_delay * (2**attempt)))
                    LOG.warning("%s - retry %d in %.2fs", code, attempt + 1, delay)
                    time.sleep(delay)
                    last_error = exc
                    continue
                raise BedrockError(f"Bedrock call failed ({code}): {exc}") from exc

            latency_ms = int((time.monotonic() - started) * 1000)
            usage = response.get("usage", {})

            tool_input = None
            for block in response.get("output", {}).get("message", {}).get("content", []):
                if "toolUse" in block:
                    tool_input = block["toolUse"].get("input")
                    break

            if tool_input is None:
                raise NoToolUseError(
                    f"Model returned no tool call; stopReason={response.get('stopReason')}"
                )

            return {
                "tool_input": tool_input,
                "input_tokens": int(usage.get("inputTokens", 0)),
                "output_tokens": int(usage.get("outputTokens", 0)),
                "latency_ms": latency_ms,
                "model_id": self.model_id,
                "stop_reason": response.get("stopReason"),
            }

        raise BedrockError(f"Exhausted {self.max_retries} retries") from last_error
