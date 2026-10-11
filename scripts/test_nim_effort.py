#!/usr/bin/env python3
"""Live-test reasoning_effort against NVIDIA NIM (build.nvidia.com).

Confirms the one thing the docs didn't pin down: whether GLM-5.3 accepts
reasoning_effort as a TOP-LEVEL JSON field (the OpenAI-SDK convention this
proxy uses), and whether low vs max actually changes thinking depth.

Usage:
    NVIDIA_API_KEY=nvapi-... uv run scripts/test_nim_effort.py [model]

Defaults to z-ai/glm-5.3. Prints, for each effort level, the HTTP outcome and
the length of the returned reasoning_content so you can see effort taking
effect (low should produce a markedly shorter reasoning trace than max).

This script makes real network calls and consumes a small number of tokens.
Set NVIDIA_API_KEY (or OPENAI_API_KEY) to a valid NIM key first.
"""
import os
import sys
import json
import urllib.request

NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = (sys.argv[1] if len(sys.argv) > 1 else "z-ai/glm-5.3")
API_KEY = os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")

# A prompt that reliably induces some reasoning but isn't huge.
PROMPT = "A train travels 60 km in 45 minutes, then 40 km in 30 minutes. What is its average speed for the whole journey in km/h? Think step by step."


def call(effort):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 1500,
        "stream": False,
        "reasoning_effort": effort,  # top-level, as the OpenAI SDK sends it
    }
    req = urllib.request.Request(
        NIM_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
            msg = payload.get("choices", [{}])[0].get("message", {})
            rc = msg.get("reasoning_content") or ""
            content = msg.get("content") or ""
            usage = payload.get("usage", {})
            return (
                f"HTTP {resp.status}  ok  "
                f"reasoning_chars={len(rc):5d}  answer_chars={len(content):4d}  "
                f"completion_tokens={usage.get('completion_tokens')}"
            )
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        return f"HTTP {e.code}  ERROR  {detail}"
    except Exception as e:  # network / parse
        return f"EXC  {e}"


def main():
    if not API_KEY:
        print("ERROR: set NVIDIA_API_KEY (or OPENAI_API_KEY) to a valid NIM key.")
        sys.exit(1)
    print(f"Model: {MODEL}\nEndpoint: {NIM_URL}\n")
    print("Testing top-level reasoning_effort envelope ...\n")
    for effort in ["low", "high", "max"]:
        print(f"  reasoning_effort={effort:>4}:  {call(effort)}")
    print(
        "\nExpectation: no 4xx on any row, and reasoning_chars for 'low' should be\n"
        "noticeably smaller than for 'max'. If a row errors with an \"unrecognized\n"
        "field\" style message, the envelope is wrong for this model and it likely\n"
        "wants the value nested (e.g. chat_template_kwargs) instead of top-level."
    )


if __name__ == "__main__":
    main()
