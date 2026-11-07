# English guide to the original hardware files

[Project overview](../README.en.md) · [Original schematic](../схема_плата/схема.pdf) · [English component workbook](../схема_плата/specificationsmd.en.xlsx) · [Russian original](../схема_плата/specificationsmd.xlsx)

Original hardware files remain unchanged. The English workbook translates text while preserving component values, formulas and formatting. This guide explains the labels and schematic without modifying connections or manufacturing files.

## Schematic PDF

All six PDF pages were visually inspected. Component identifiers, net names, pin labels and title blocks are already Latin-script engineering notation or English. No Russian prose labels needing replacement were found. The same schematic therefore serves both language versions.

| PDF page | Contents for navigation |
| --- | --- |
| 1 | Supply and voltage regulators |
| 2 | RX input path and PCM1808 DA6 |
| 3 | TX amplifier/coupling network, reference circuits and PCM1808 DA9 |
| 4 | PCM5102A DA11 and its two output filters |
| 5 | DSP clocking, power, EEPROM, reset and control interface |
| 6 | DSP signal interfaces and provisioned optical S/PDIF output |

The page index above refers to the PDF page order, not the drawing's printed sheet field. The block diagram in [README.en.md](../README.en.md#block-diagram) translates the explanatory diagram labels. It is an overview and does not replace tracing connections on the schematic.

## Component workbook

The single sheet is named `specificationsmdcoil`. Every Russian text cell is a repeated column heading. The following table covers all fourteen occurrences:

| Original cells | Russian | English |
| --- | --- | --- |
| A1, A32 | Номер | Number |
| B1, B32 | Метка | Reference designator |
| C1, C32 | Значение | Value |
| D1, D32 | Тип | Type |
| E1, E32 | Кол-во | Quantity |
| F1, F32 | Цена/шт | Unit price |
| G1, G32 | Цена | Price |

Part numbers, component designators and type codes remain unchanged. The original values `4,7K`, `4,3K`, `2,2K` and `2,2OM` use a decimal comma: read them as 4.7 kΩ, 4.3 kΩ, 2.2 kΩ and 2.2 Ω respectively. `uF` means µF and `v`/`V` means volts. The original workbook is retained byte-for-byte. The [English XLSX](../схема_плата/specificationsmd.en.xlsx) translates all fourteen heading cells and Russian built-in style/theme names. Its existing Latin sheet name, all 215 numerical cells (including formula caches), 54 formulas, cell formatting and print settings are preserved. The headings alone do not establish a currency, current market prices or purchasing availability.

The spreadsheet authoring tool was used to edit, recalculate and preview the translation. Because its export omitted existing print settings, the authored text was transferred into a copy of the original XLSX package. Only text was substituted; unaffected ZIP members were verified byte-for-byte. Both heading rows were visually reviewed and a formula-error scan returned no matches.

## Models, build outputs and photographs

CAD/mesh geometry, PCB Gerber/drill files and compiler-generated parameter identifiers have no language-specific replacement here. Their original filenames remain stable. `корпус` means enclosure, `схема_плата` means schematic/board, `сигма_проект` means SigmaStudio project, and `фото` means photographs.

Photographs are shared originals with translated captions and alternative text in README.en.md and on the English website. No display, PCB marking or measurement trace has been retouched. The unchanged saved compiler report already uses English.
