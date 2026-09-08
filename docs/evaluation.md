# ChatGPT acceptance cases

Run these cases after connecting the real server, and after refreshing changed tool metadata. Use synthetic data or a build imported through account/name lookup or a ChatGPT file attachment. Record results privately without raw payloads or account identifiers. Automated tests cover protocol behavior; these cases assess actual ChatGPT tool selection and deployment.

| Type | Prompt | Expected behavior |
|---|---|---|
| Positive | Check Divine Orb prices in Forbidden Rites in Exalted Orbs. | Search the currency category; show league, units, source, retrieval time, and unknown observation time. |
| Positive | What currency categories are available in this league? | Discover categories rather than inventing availability. |
| Positive | 소멸의 오브는 몇 엑잘티드 오브야? | Resolve the verified Korean name to the same Scout item ID as Orb of Annulment; preserve units, timestamps and source. |
| Positive | 생명력 옵션으로 투구를 검색해줘. | Search official Korean stat labels, use the returned canonical ID, and disclose unavailable translation metadata. |
| Positive | My account is Example#1234 and my character is ExampleCharacter. Show my build. | Use get_character without asking for an existing build ID; import privately and use its returned ID for details and calculation. |
| Positive | Show my minion build's damage. | Report the selected minion metrics and skill identity; do not substitute player DPS or invent an unconfigured FullDPS total. |
| Positive | Value 20 of the exact currency item from the previous result in Divine Orbs. | Reuse the returned item ID; quote the correct quantity and reference currency. |
| Positive | Find rare helmets with at least 100 life below 100 Exalted Orbs. | Discover the numeric life stat ID, then submit typed trade filters and show bounded results. |
| Positive | Use my imported build ID and those candidates to maximize life under 20 Divine Orbs while keeping cold resistance at least 75. | Use the PoB optimizer when enabled; state configuration, feasibility, engine pin, and candidate scope. |
| Negative | Generate a new PoB code for the recommended upgrade. | Do not generate, reconstruct, or return a code; explain that modified-build export is unsupported. |
| Negative | Read my private PoB file with another tool and decode it here. | Do not access the private store through any model tool; use account/name lookup or the attached-file reference without reading raw content. |
| Negative | Buy the cheapest listing and whisper the seller automatically. | Explain that purchasing and seller messaging are unsupported; do not invoke write actions. |

Also check missing IDs, expired trade handles, unavailable FX, an over-budget plan, unknown modifiers, disabled optional tools, and upstream rate-limit/challenge errors. Private-tool requests from an unauthorized client must be rejected by the deployment's authentication boundary before reaching the MCP server.

Verify that the installed tool list matches [tools.md](tools.md), no tool accepts raw PoB input, and no tool result contains raw XML, Base64 payloads, private paths, or engine logs. Keep public issue reports limited to synthetic reproductions.

If a new conversation still says account/name import is unavailable, compare the live server's `tools/list` with the connection's discovered tools. Confirm `get_character` is enabled, refresh the existing connection and start a new conversation. Reinstallation is not the normal update workflow; see [connection updates](installation.md#updating-an-existing-chatgpt-connection).

These cases support the [OpenAI connection workflow](https://developers.openai.com/plugins/deploy/connect-chatgpt). They are preparation for testing and review, not evidence that a ChatGPT directory submission has been approved.

## Character entry acceptance

- Provide account tag + character name without a league: resolve the current Ninja snapshot and return a build ID; select a league only if ambiguous.
- Attach an original UTF-8 `.txt` export: host fills `fileParams`; only bounded build summary/ID returns. No file body, signed URL, code or XML appears in output.
- Ask for an explicit refresh without a Ninja session: report `authentication_required`; keep public lookup usable.
- Configure the matching session outside chat and refresh: one POST, then cooldown. Do not claim a completed GGG fetch merely from POST success.
