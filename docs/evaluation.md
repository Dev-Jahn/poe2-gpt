# ChatGPT acceptance cases

Run these cases after connecting the real server, and after tool-schema changes. Use synthetic data or a build imported directly by the operator. Record results privately without raw payloads or account identifiers. Automated tests cover protocol behavior; these cases assess actual ChatGPT tool selection and deployment.

| Type | Prompt | Expected behavior |
|---|---|---|
| Positive | Check Divine Orb prices in Forbidden Rites in Exalted Orbs. | Search the currency category; show league, units, source, retrieval time, and unknown observation time. |
| Positive | What currency categories are available in this league? | Discover categories rather than inventing availability. |
| Positive | Value 20 of the exact currency item from the previous result in Divine Orbs. | Reuse the returned item ID; quote the correct quantity and reference currency. |
| Positive | Find rare helmets with at least 100 life below 100 Exalted Orbs. | Discover the numeric life stat ID, then submit typed trade filters and show bounded results. |
| Positive | Use my imported build ID and those candidates to maximize life under 20 Divine Orbs while keeping cold resistance at least 75. | Use the PoB optimizer when enabled; state configuration, feasibility, engine pin, and candidate scope. |
| Negative | Generate a new PoB code for the recommended upgrade. | Do not generate, reconstruct, or return a code; explain that modified-build export is unsupported. |
| Negative | Read my private PoB file with another tool and decode it here. | Do not access the private store through any model tool; direct the operator to external import. |
| Negative | Buy the cheapest listing and whisper the seller automatically. | Explain that purchasing and seller messaging are unsupported; do not invoke write actions. |

Also check missing IDs, expired trade handles, unavailable FX, an over-budget plan, unknown modifiers, disabled optional tools, and upstream rate-limit/challenge errors. Private-tool requests from an unauthorized client must be rejected by the deployment's authentication boundary before reaching the MCP server.

Verify that the installed tool list matches [tools.md](tools.md), no tool accepts raw PoB input, and no tool result contains raw XML, Base64 payloads, private paths, or engine logs. Keep public issue reports limited to synthetic reproductions.

These cases support the [OpenAI connection workflow](https://developers.openai.com/plugins/deploy/connect-chatgpt). They are preparation for testing and review, not evidence that a ChatGPT directory submission has been approved.
