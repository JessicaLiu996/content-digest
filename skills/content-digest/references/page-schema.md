# Digest JSON schema

Create `digest.json` in a result directory containing `transcript.json`, `reading-index.json`, `task-state.json`, and transcript attachments. Source metadata and quoted excerpts are read from these records, not invented by the renderer.

```json
{
  "title": "Reading-page title",
  "subtitle": "A brief description of the source",
  "thesis": "The central idea with its attribution preserved",
  "read_parts": [1],
  "events": [{"title": "Topic", "text": "One sentence of context", "insight": 1}],
  "insights": [{
    "kind": "Speaker view",
    "title": "Main insight",
    "claim": "The claim and explanation",
    "example": "Evidence or example from the source",
    "limit": "A material qualification, or an empty string",
    "ref": {"start": 0, "end": 30},
    "details": [{"title": "Supporting detail", "text": "Additional evidence", "ref": {"start": 30, "end": 60}}]
  }],
  "quotes": [],
  "chapters": [{"title": "Opening", "text": "The question discussed", "ref": {"start": 0, "end": 60}}],
  "notes": ["A material source or recognition limitation"]
}
```

This example shows the shape; use times and text from the actual transcript.

- `read_parts` must list **all parts actually read**, in the order in `reading-index.json`. Merely seeing the index does not count as reading it.
- `events[].insight` is a one-based insight index.
- `kind` is `Speaker view` or `Source statement`.
- Every insight has `title`, `claim`, `example`, `limit`, `ref`, and a `details` array. The limit can be empty; details and quotes can be empty.
- A quote is `{"text": "Exact short excerpt", "ref": {"start": 0, "end": 30}}`; it must match the transcript in that interval.
- Times are seconds from the source start. Intervals must be positive and within the recorded duration. Chapters are chronological and non-overlapping.
- For untimed text, use `ref: null` and `chapters: []`. Do not generate artificial times.
- `notes` is an array of non-empty strings; it may be empty.

The English interface can display content in other languages. Source text is rendered as text, never executable HTML. The generated page embeds its digest data and links relatively to `transcript.md`. Keep the editable JSON files for later corrections.
