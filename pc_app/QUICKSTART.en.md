# FerroDSP Lab — portable Windows version

[Русский](QUICKSTART.md) | [English](QUICKSTART.en.md)

1. Download `FerroDSP-Lab-…-windows-x64.zip` from the repository's [Releases](https://github.com/neuroandriyanov/FerroDsp/releases).
2. Extract the **entire ZIP** into a writable directory, such as `Documents\FerroDSP-Lab`.
3. Run `FerroDSP-Lab.exe`. Python, pip, SigmaStudio and a separate video codec are not required to run this application. No internet connection is needed during use.

Keep the `_internal` folder with the EXE. Settings and recordings are written to
`UserData/local` and `UserData/recordings` beside the EXE. To update, extract a new
version separately and copy your `UserData` into it, keeping a backup. On a different
setup, calibrate the coil plane, empty background and phase baseline again.

## Equipment

Windows 10/11 x64, recording disk space (minimum checked: 2 GB), a RealSense D415
on USB 3, and a S/PDIF input exposing **96 kHz stereo PCM24, WASAPI exclusive**.
Windows device drivers are required. PCM24 describes the capture format, not a
measurement of effective hardware resolution.

Signal plots require the [PC Stream DSP project](../сигма_проект/FerroDSP_PC_Stream/FerroDSP_PC_Stream.dspproj)
with the `ferrodsp-am-iq-v1` protocol. An arbitrary stereo signal is not four I/Q
channels. See `Source/pc_app/resources/transport-protocol.json` inside the portable package.

The application connects automatically. Missing devices leave the window available
with an error message. Select the optical input in **Настройки захвата** (Capture settings).
Close other applications using the camera or audio input. The application does not
change detector firmware or settings. Metal classification is not implemented yet.

Before recording, add a target to the table and configure the coil plane and empty
background. The current UI is Russian. Main controls: **Параметры камеры** (Camera settings),
**Пустой фон** (Empty background), **Графики и масштаб** (Plots and scale),
**Добавить образец** (Add sample), **Начать запись** (Start recording), **Остановить** (Stop).
The preview offers color, depth and adjustable overlays; the right pane shows phase,
amplitude and distance. Detailed technical documentation: `Source/pc_app/README.md` (Russian).

## Diagnostics and control

Start without connecting devices:

```powershell
.\FerroDSP-Lab.exe --no-connect
```

Check bundled libraries, decoder and file recording without device capture:

```powershell
Start-Process -FilePath .\FerroDSP-Lab.exe -ArgumentList '--self-test self-test.json' -Wait
Get-Content .\self-test.json
```

The result should contain `"ok": true`. Error log: `UserData/local/application.log`.
`FERRODSP_DATA_DIR` selects another writable data directory. The local API address
and per-process token are in `UserData/local/control.json`; do not publish or transfer
them between PCs. The README documents the API.

This is a preview release tested on the current Windows bench. Test the ZIP on the
destination PC as well. Synchronization uses a common PC timeline; physical latency
between camera and audio has not been calibrated.
