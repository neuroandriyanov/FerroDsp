# Russian originals and English translations

[Русский](TRANSLATIONS.md) | [English](TRANSLATIONS.en.md)

Russian is the original authoring language. New material can be published in Russian immediately; English is added after translation and review. A missing or outdated translation does not block Russian publication.

## Project documents

Keep the Russian file at its existing path. Place English versions alongside it: `README.en.md`, `docs/SETUP.en.md`. Translate the complete document, including tables, captions and limitations. Links between English documents should target English counterparts where available. Add explicit language links. Preserve command names, APIs, pins, registers and raw measurement filenames.

Preserve numerical logs, photographs, firmware, CAD and historical manifests. For text embedded in diagrams, plots and tables, add an English derivative or precise annotations linked to the original. Never retouch instrument readings. An artistic illustration is not evidence of the hardware design.

## Checking freshness

From the repository root:

```sh
node tools/translations.mjs status
node tools/translations.mjs status --all
```

`MISSING` means a Russian document has no registered translation; `STALE` means its source has changed; `CHANGED` means the English file changed after review; `BROKEN` means a registered file is missing. `CURRENT` only confirms that the stored hashes match; it is not an automatic assessment of translation quality.

After completing the translation and checking numbers, units, links and engineering meaning, record the reviewed pair:

```sh
node tools/translations.mjs record README.md README.en.md
```

This saves both SHA-256 hashes in `translations.json`. Do not run `record` automatically when Russian text changes: that would conceal an outdated translation. Normal `status` reports outdated translations without blocking Russian publication; `status --strict` requires a complete, current set before releasing translations. A manifest can constrain `sourceRoots` and list `excludedSources` explicitly; document the reasons for exclusions.

## Website pages

A Russian project stays in `src/content/projects/<id>.md`. Add its translation at `src/content/projects/en/<id>.md`, with `lang: en`, `translationOf: <id>` and `draft: false` after review. Mark unfinished translations `draft: true`. Russian addresses remain unchanged; English addresses begin with `/en/`. The language switch and metadata only connect published pairs. A translation without a published Russian original is not displayed.

Templates and CSS are shared. Interface text lives in `src/i18n/ru.json` and `src/i18n/en.json`. Check matching keys, line wrapping and mobile layouts. Translating a project does not require copying templates or styles.

Before a website release, check the build, links, language pairs, production and preview SEO, and NeuroEngineer answers in both languages. Publishing on GitHub and deploying the hosted website are separate actions.
