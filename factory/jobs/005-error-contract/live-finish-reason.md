# Live finish_reason check against the real upstream (job 005, 2026-11-14)

Direct streamed requests to every configured tier model with the user's restarted .env (5 keys; values never printed). Three cases per model: short text, a tool call, and a `max_tokens` cut. `finish_reasons` lists every non-null finish_reason seen. A stream with chunks but no finish_reason would hit the new truncated-stream error.

| tier | model | case | chunks | finish_reasons | error | secs |
|---|---|---|---|---|---|---|
| BIG_MODEL | stepfun-ai/step-5-preview | text | 12 | stop | - | 1.2 |
| BIG_MODEL | stepfun-ai/step-5-preview | tool | 11 | tool_calls | - | 1.2 |
| BIG_MODEL | stepfun-ai/step-5-preview | length | 5 | length | - | 0.4 |
| BIG_MODEL | nvidia/nemotron-3-ultra-550b-a55b | text | 8 | stop | - | 0.9 |
| BIG_MODEL | nvidia/nemotron-3-ultra-550b-a55b | tool | 11 | tool_calls | - | 2.7 |
| BIG_MODEL | nvidia/nemotron-3-ultra-550b-a55b | length | 5 | length | - | 0.8 |
| BIG_MODEL | deepseek-ai/deepseek-v4.1-flash | text | 0 | - | APITimeoutError | 120.0 |
| BIG_MODEL | deepseek-ai/deepseek-v4.1-flash | tool | 0 | - | APITimeoutError | 120.1 |
| BIG_MODEL | deepseek-ai/deepseek-v4.1-flash | length | 0 | - | APITimeoutError | 120.1 |
| MIDDLE_MODEL | mistralai/mistral-large-4-1t-a52b | text | 10 | stop | - | 5.4 |
| MIDDLE_MODEL | mistralai/mistral-large-4-1t-a52b | tool | 20 | tool_calls | - | 2.2 |
| MIDDLE_MODEL | mistralai/mistral-large-4-1t-a52b | length | 5 | length | - | 3.0 |
| MIDDLE_MODEL | minimaxai/minimax-m3.1-flash | text | 0 | - | InternalServerError 503 | 0.1 |
| MIDDLE_MODEL | minimaxai/minimax-m3.1-flash | tool | 4 | tool_calls | - | 6.3 |
| MIDDLE_MODEL | minimaxai/minimax-m3.1-flash | length | 13 | length | - | 30.3 |
| MIDDLE_MODEL | z-ai/glm-5.3-flash | text | 0 | - | APITimeoutError | 120.0 |
| MIDDLE_MODEL | z-ai/glm-5.3-flash | tool | 0 | - | APITimeoutError | 120.1 |
| MIDDLE_MODEL | z-ai/glm-5.3-flash | length | 0 | - | APITimeoutError | 120.1 |
| MIDDLE_MODEL | nvidia/nemotron-3.5-super-vl-120b-a12b | text | 11 | stop | - | 0.7 |
| MIDDLE_MODEL | nvidia/nemotron-3.5-super-vl-120b-a12b | tool | 22 | tool_calls | - | 0.9 |
| MIDDLE_MODEL | nvidia/nemotron-3.5-super-vl-120b-a12b | length | 5 | length | - | 0.4 |
| MIDDLE_MODEL | deepseek-ai/deepseek-v4.1-flash | text | 0 | - | APITimeoutError | 120.0 |
| MIDDLE_MODEL | deepseek-ai/deepseek-v4.1-flash | tool | 0 | - | APITimeoutError | 120.1 |
| MIDDLE_MODEL | deepseek-ai/deepseek-v4.1-flash | length | 0 | - | APITimeoutError | 120.1 |
| MIDDLE_MODEL | poolside/laguna-xs-2.1 | text | 3 | stop | - | 0.3 |
| MIDDLE_MODEL | poolside/laguna-xs-2.1 | tool | 14 | tool_calls | - | 0.4 |
| MIDDLE_MODEL | poolside/laguna-xs-2.1 | length | 13 | length | - | 0.2 |
| MIDDLE_MODEL | meta/muse-glimmer-30b | text | 103 | stop | - | 13.2 |
| MIDDLE_MODEL | meta/muse-glimmer-30b | tool | 38 | tool_calls | - | 9.5 |
| MIDDLE_MODEL | meta/muse-glimmer-30b | length | 8 | length | - | 1.4 |
| SMALL_MODEL | nvidia/nemotron-3.5-lightning-30b-a3b | text | 63 | stop | - | 1.2 |
| SMALL_MODEL | nvidia/nemotron-3.5-lightning-30b-a3b | tool | 7 | tool_calls | - | 0.5 |
| SMALL_MODEL | nvidia/nemotron-3.5-lightning-30b-a3b | length | 7 | length | - | 0.2 |
| SMALL_MODEL | openai/gpt-oss-20b | text | 0 | - | APITimeoutError | 120.0 |
| SMALL_MODEL | openai/gpt-oss-20b | tool | 0 | - | APITimeoutError | 120.1 |
| SMALL_MODEL | openai/gpt-oss-20b | length | 0 | - | APITimeoutError | 120.1 |

## Result

- Every model that answered sent a non-null finish_reason on every streamed case: `stop` for text, `tool_calls` for the tool call, `length` for the max_tokens cut. No case produced chunks without a finish_reason, so no configured model would trip the truncated-stream error on these replies.
- Models that answered: stepfun-ai/step-5-preview, nvidia/nemotron-3-ultra-550b-a55b, mistralai/mistral-large-4-1t-a52b, minimaxai/minimax-m3.1-flash (one transient 503, then `stop` on retry), nvidia/nemotron-3.5-super-vl-120b-a12b, poolside/laguna-xs-2.1, meta/muse-glimmer-30b, nvidia/nemotron-3.5-lightning-30b-a3b.
- NOT VERIFIED: deepseek-ai/deepseek-v4.1-flash (BIG fallback 3 and MIDDLE), z-ai/glm-5.3-flash (MIDDLE), openai/gpt-oss-20b (SMALL fallback 2). They returned no bytes at all within 120 s, and again within 90 s on a parallel retry, streaming and non-streaming, on two different keys. That is an upstream availability problem, not a finish_reason omission, and it is the same before and after job 005. These three are fallbacks only; the primaries of each tier passed.
- Not covered: a reasoning model with thinking on, and long multi-turn replies.
