# Publishing in Russian and translating into English

[Русский](TRANSLATION.md) | **English**

Russian is the primary language of the author's documentation. New information can be published in Russian immediately; the completed English translation is added in a separate change.

1. Create or update the Russian document at its normal path. Preserve existing file paths, component designators and original measurements.
2. Add a complete translation alongside it: `README.en.md`, `NOTICE.en.md`, `name.en.md` or `name.en.txt`. Add a language link to both versions. Do not show links to translations that do not yet exist.
3. In the English version, link to English documents and translated captions. Photographs, binary projects, raw data, schematics with international notation and full third-party license texts remain shared.
4. Check numerical values, units, tolerances, designators, commands, formulas and the distinction between measurements, calculations and assumptions. Do not shorten limitations or turn hypotheses into facts.
5. After verification, update the matching entry in `i18n/manifest.json`: `source` and `target` paths and the SHA-256 of both versions. Record a new source hash only after bringing its translation up to date.

A change to the Russian file after translation makes the previous translation stale. This does not prevent publication of the Russian update; update the English version in the next stage. Hashes identify exact file bytes, including language navigation.

## Materials in this package

- `README.md` and `NOTICE.md` have complete English versions.
- `схема_плата/specificationsmd.en.xlsx` contains English headings for the original bill of materials. Numbers, reference designators, component names and formulas are preserved. The original specification remains at its previous path.
- All six pages of `схема_плата/схема.pdf` were reviewed: labels, net names and the title block are already in English. The same unmodified PDF serves both languages.
- Photographs, Gerber files, enclosure models and binary SigmaStudio files are shared. Photograph captions and the block diagram are translated in the English README.
- The full MIT and CERN-OHL-P-2.0 texts are unchanged; the explanation of licensing scope is translated in `NOTICE.en.md`.

Do not mark a file as translated if only a summary has been prepared. New material that has not yet been translated remains available in Russian with its language identified.
