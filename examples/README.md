# Reproduce the reading-page example

This original fixture was written for this repository. It is not copied from a podcast, and there is no corresponding audio recording. The timestamps in `source.srt` are illustrative test data, not measured speech timing.

The included digest was written after reading all five source segments. It demonstrates source attribution, qualifications, expandable evidence, an exact short quotation, and a complete chapter map.

## Rebuild the included page

From the repository root:

```bash
python3 skills/content-digest/scripts/build_reader.py examples/sample/digest.json
```

Open [sample/ContentDigest.html](sample/ContentDigest.html) in a browser. GitHub itself displays HTML source rather than running this local page.

## Reproduce from the source fixture

Choose a fresh output directory:

```bash
python3 skills/content-digest/scripts/import_text.py examples/source.srt \
  --title "A smaller first release — authored example" --output /tmp/content-digest-example
cp examples/sample/digest.json /tmp/content-digest-example/digest.json
python3 skills/content-digest/scripts/build_reader.py /tmp/content-digest-example/digest.json
```

Open the resulting HTML file. It loads its content without network requests; the full transcript is a separate local attachment. Using the same output path twice is intentionally rejected to preserve existing results; choose a new empty directory for another run.

## With your own text

Import your own `.txt` or `.srt`, ask your agent to read every range in `reading-index.json`, and write a new `digest.json` following the [schema](../skills/content-digest/references/page-schema.md). Do not reuse the sample summary for different source material. Untimed TXT has no timestamp buttons or chapters unless genuine timing is supplied later.

## What is covered

This example covers text import, index creation, quotation matching, HTML generation, and reader interaction. It does not download audio, load a Whisper model, or validate real-media timestamps.
