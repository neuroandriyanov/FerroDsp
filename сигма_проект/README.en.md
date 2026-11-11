# SigmaStudio projects

[Русский](README.md) | [English](README.en.md)

Two organized projects for **SigmaStudio 4.7 / ADAU1452**, checked on 11 November 2026. Blocks are arranged by functional signal paths. Connections, parameters and the DSP program were preserved; each directory contains `publication-verification.json` with comparison results.

| Project | Purpose | TX | DSP rate | Build result |
| --- | --- | --- | --- | --- |
| [Phase Tracking](FerroDSP_Phase_Tracking/FerroDSP_Phase_Tracking.dspproj) | Automatic balancing and background tracking around zero | 15.2 kHz, −30 dB | 96 kHz | 0 errors / 0 warnings; 1251 cycles, 41%; PM 1571/8192 |
| [PC Stream](FerroDSP_PC_Stream/FerroDSP_PC_Stream.dspproj) | Four complex inputs over S/PDIF for [FerroDSP Lab](../pc_app/QUICKSTART.en.md) | 15.2 kHz, −18 dB | 96 kHz | 0 errors / 0 warnings; 23% cycles; PM 822/8192 |

These are alternative configurations. Phase Tracking outputs do not follow the PC Stream protocol. TX levels are digital generator settings, not power in watts. Publication builds used **Link Compile Connect**; no DSP download or EEPROM write was performed.

## Phase Tracking

TX excitation and audio output are at the top, followed by RX filtering/phase detection and TX measurement. Below are auto-balance constants, timers and integrator, quiet-background checks, the original audio logic and diagnostic meters. Block names are preserved for parameter mapping.

After startup: 0–5 s settling; 5–25 s initial acquisition (`AB_IntegralGain=0.00064`); after 25 s slow tracking (`LT_SlowGain=0.00032`). Slow tracking is enabled after the error remains continuously within ±0.015 relative units for 2 s. Tracking freezes outside that window. A very weak, slow target inside the window can be absorbed into the background estimate.

Initial delay control is 0.035; the integrator is limited to ±122.88 and scaled by 1/8192, producing a control range of 0.020…0.050. These values are neither seconds nor degrees. `Switch1` is saved ON. The native `RealTimeDisplay1` graph / `T22` node shows relative balance-detector output. The 700 Hz audio generator is set to −18 dB.

## PC Stream

Four matching rows: input → I/Q reference multiplication → fourth-order 100 Hz Butterworth low-pass → live/calibration selection → scale/bias → amplitude modulation. I/Q sums, pilot and S/PDIF are on the right. TX excitation, references and shared constants are at the top.

| DSP input | Signal | Transport carrier |
| --- | --- | --- |
| 0 | RX0, first receive-coil half | 1500 Hz |
| 1 | RX1, second receive-coil half | 3700 Hz |
| 16 | TX coil-side voltage | 5900 Hz |
| 17 | TX amplifier-side voltage | 8100 Hz |

The left optical channel carries I, the right carries Q. Pilot: 10300 Hz. `PC_Mode=1` (LIVE) is saved; audio output is muted. PC decoding uses a 40 ms window with 10 ms hop: 100 I/Q sets per second. This protocol does not transmit four broadband ADC streams.

[Full protocol and connection points](../pc_app/resources/transport-protocol.json) · [Transport calibration](../pc_app/resources/transport-calibration.json) · [Measurement results](../docs/measurements/2026-11-10_11/README.en.md).

## Opening and building

Download the entire repository and open the selected `.dspproj` in SigmaStudio 4.7. USBi is not required for viewing or compilation. Use **Link Compile Connect** to check a build without replacing the device program. **Link Compile Download / F7** downloads the project to DSP; EEPROM programming is a separate action. Compiled `Program.bin`, parameters and reports are in the adjacent `*_IC 1` directory.

Optical transport calibration applies to the documented settings and Creative G3 path. Recheck it after modifying the DSP or receiver. The algorithm does not yet reliably identify metal type, size or depth.

The historical [Ferrodsp_v1_exp2](Ferrodsp_v1_exp2/Ferrodsp_v1_exp2.dspproj) is retained separately. Author-created settings are MIT licensed; third-party blocks and Analog Devices tools retain their own licensing terms, see [NOTICE](../NOTICE.en.md).
