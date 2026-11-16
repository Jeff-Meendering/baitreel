# The Field Guide

The Field Guide is the catalogue of scam tactics Baitreel can label. Each
tactic is one YAML file in [`tactics/`](tactics/).

Two rules make it trustworthy:

1. **The pipeline can only label a moment with a tactic from this catalogue.**
   A model cannot invent a new one.
2. **The advice shown to viewers is copied from the card, word for word.**
   No model ever writes safety advice.

So improving Baitreel's accuracy and tone is often a matter of improving a
card, and that needs no programming.

## What a card contains

| Field | What it is for |
|---|---|
| `id` | Lowercase words joined by hyphens. Must match the file name. |
| `name` | The memorable name on the stamp. 24 characters at most. |
| `plain_label` | One plain line under the name: what the scammer is doing. |
| `description` | A sentence or two for the model and for readers of this guide. |
| `sounds_like` | Example lines. They help the model, and each card is tested against its own examples. |
| `cues` | Patterns (regular expressions) for the keyword spotter and for highlighting. |
| `why_it_works` | Why the tactic is effective on anyone. |
| `counter_move` | What to do instead. Shown on screen, so 32 words at most. |
| `source` | The published advice the counter-move relies on. An `https` link is required. |
| `status` | `draft` until a human reviewer has checked the card against its source, then `reviewed`. |

## Adding or changing a card

1. Copy an existing file in `tactics/` and edit it.
2. Base the `counter_move` on advice from a consumer-protection body (for
   example the FTC, AARP, Action Fraud or Scamwatch) and link it in `source`.
3. Write about what the scammer does, never about what the person "fell for".
   A card that uses blaming words fails validation.
4. Run the checks:

   ```bash
   uv run baitreel guide --check
   uv run pytest tests/test_fieldguide.py
   ```

5. Open a pull request. A maintainer reads the card against its source
   before changing `status` to `reviewed`.

## License

The Field Guide (everything in this folder's `tactics/` directory) is
licensed under [Creative Commons Attribution 4.0 International][cc-by], so
educators, libraries and other tools can reuse it with credit. See
[LICENSE](LICENSE). The rest of Baitreel is MIT licensed.

[cc-by]: https://creativecommons.org/licenses/by/4.0/
