# Reading-page output

Deliver one interactive `ContentDigest.html` page by default, with the full transcript attached. Aim for about three minutes of main reading when the source warrants it; shorter material should stay short. Keep supporting detail and the chapter list expandable rather than creating multiple summary tiers.

## Content sequence

1. **Overview:** the source's central idea or most important attributed conclusion, with its title and duration when known.
2. **Topic map:** one sentence per event or issue. Knowledge explanations can use topics; do not invent news events. Link to relevant insights.
3. **Insights:** usually three to five, determined by the material. Each needs its claim, explanation, evidence/example, important limits or disagreement, and source reference where available. Keep crucial qualifications visible, not hidden in details.
4. **Quotations:** usually one or two short, reliable excerpts that match the transcript. Punctuation/whitespace normalization is allowed; rewriting a sentence as a stronger quote is not. Omit questionable recognition or uncertain names. Recognition-based quotes are not audio-verified unless checked.
5. **Chapters:** chronological coverage of the source's main topics, including useful material omitted from the main digest. Show timestamps only when supplied by the source or recognition output.

English main copy usually fits around 450–650 words; Chinese copy can target roughly 900–1,200 characters when requested. These are reading-experience guides, not quotas. Include visible evidence and quotations in the main length. The renderer estimates reading time; it does not prove the editorial target has been met.

## Visuals and interaction

Use the bundled `assets/reader.html` and `scripts/build_reader.py`. The visual baseline is pale gray paper, white cards, dark readable text, subtle boundaries, and restrained link color. It does not automatically switch to dark mode. No external fonts, chart libraries, analytics, or background network requests are included.

Keep insights and evidence together. Use textual attribution labels (`Speaker view` or `Source statement`); neither means independently verified fact. Prefer topic maps and clear cards. Use comparisons or sequences only when the source supports them; do not invent scores or causal diagrams.

Check expandable detail, chapter navigation, excerpt dialogs, source links, and the full-transcript attachment on desktop and narrow screens with keyboard access. YouTube URLs can include a timestamp; Apple Podcasts opens the episode and requires manual seeking. Imported text without an external URL has no source playback link.

## Fidelity

Read all indexed parts before merging and compressing. Preserve numbers, assumptions, counterexamples, and attribution. Do not turn a prediction or claim into an established fact by removing words such as “might” or “the speaker argues.”

Preserve the full transcript's original language, with consistent Simplified Chinese orthography where applicable. Default digest prose to English unless requested otherwise. Skip introductions, advertisements, and uninformative repetition in the digest while retaining stories or counterexamples needed to understand the argument.

Do not add outside research or action advice by default. Label any requested extension as the editor's contribution. Place material uncertainty with the affected insight and general recognition notes at the end.

## Finish

Write `digest.json` using the [schema](page-schema.md), render it, inspect it, and test the actual interactions. The renderer checks referenced times, chronological chapters, read-part IDs, and quote matching; those checks do not prove that the agent read or interpreted the source correctly. Only mark summary completion after content and UI checks pass.
