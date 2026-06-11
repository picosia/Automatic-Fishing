# Sensei constellation click helper

This tool automates the constellation mini-game by reading the star field from the screen, finding the moving constellation pattern, moving it onto the matching background stars, and clicking.

The current implementation does not depend on a fixed success screenshot or a fixed star map. It supports random constellation patterns and random background stars because both are detected fresh on each run.

## How it works

1. Captures the current star field.
2. Detects the moving magenta/white constellation pattern.
3. Moves the cursor through a short sweep and captures several frames.
4. Builds a merged set of fixed background stars while excluding the moving overlay area in each frame.
5. Matches the current random pattern against the fixed star set.
6. Clicks only when enough vertices match.

This sweep is intentional: if the moving ring/line covers a background star, a nearby cursor position usually reveals that star in another frame.

The game also removes decoy stars as time passes. If confidence is low, the script retries for a few seconds, which makes late clicks easier and safer.

## Run

Open the mini-game, run the BAT, and return focus to the game window during the startup delay:

```powershell
.\run_sensei_click.bat
```

By default the BAT waits 4 seconds before capturing the live screen. It then moves the cursor to the center of the star field and starts the sweep from there. You no longer need to place the cursor manually inside the star field.

If the game is running as administrator, run the BAT or PowerShell as administrator too.

## Auto loop

To wait for the fishing prompt, click `自分で釣る`, clear the constellation mini-game, and then keep waiting for the next prompt:

```powershell
.\run_sensei_auto_loop.bat
```

Stop the loop with `Ctrl+C` in the console.

## Scheduled loop

To run across game-time sessions, first collect the two fixed start coordinates:

```powershell
.\run_cursor_position.bat
```

Move the cursor to each target and press `F12`; write the printed coordinates into `auto_fishing_start.json`.

Then run:

```powershell
.\run_sensei_scheduled_loop.bat
```

This waits for ET `18:10`, clicks the two configured start points, runs the auto loop while waiting for `自分で釣る`, and ends the session only while waiting for the next `自分で釣る` after ET `05:50`. If started during the active ET window, it begins after the startup delay.

## Dry run

Print the detected movement without the final click:

```powershell
.\run_sensei_click_dry.bat
```

Move without clicking:

```powershell
& 'C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\sensei_click.py --move-only
```

## Useful options

By default the script auto-detects the star field rectangle from the game UI border.
The rectangle is detected once at startup and then locked for the whole run, because the mini-game background brightens over time and can make repeated auto-detection drift.

For the attached debug screenshot, auto-detection resolves to roughly:

```text
670,363,597,289
```

The old fixed rectangle for the original 1904x1006 screenshots was:

```text
663,282,592,286
```

If auto-detection fails, set it manually:

```powershell
& 'C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\sensei_click.py --rect 663,282,592,286
```

To wait longer for decoy stars to disappear:

```powershell
& 'C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\sensei_click.py --retry-until 14
```

To change the startup delay:

```powershell
& 'C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\sensei_click.py --start-delay 4
```

To make the cursor sweep wider or narrower:

```powershell
& 'C:\Users\libis\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\sensei_click.py --offsets "0,0;120,0;-120,0;0,90;0,-90"
```

## Notes

- The moving pattern is made of rings/lines, so background stars may still be partly visible through it. The script still sweeps because overlay pixels can merge with star pixels and make center detection unstable.
- Background stars are kept only when they appear at the same screen position in multiple sweep frames. This prevents the moving constellation's own glow from being mistaken as a fixed background star.
- If the detected moving line touches the star-field edge or spans nearly the whole field, the frame is discarded as a bad capture. This catches cases where the command prompt was still in front or the cursor sweep clipped the pattern.
- The game draws the constellation pattern offset from the Windows cursor position. The script first measures that offset and recenters the visible constellation before sweeping.
- For safety, low-confidence matches are not clicked.
- The old calibrated screenshot mode was removed from the normal flow because the constellation pattern changes every attempt.

## Debug output

`run_sensei_click.bat` saves debug captures under:

```text
debug_last\YYYYMMDD_HHMMSS
```

If detection fails, check or share:

- `log.txt`
- `attempt00_initial_full.png`
- the latest `*_field.png` files

The full image has a red rectangle showing the area the script is cropping as the star field.

Constellation debug image saving can be changed with:

```text
--constellation-debug-images full-images
--constellation-debug-images minimal-images
```

`full-images` is the default and saves images as before. `minimal-images` keeps constellation debug images in memory during successful solves and writes them only when the solver gives up on that mini-game.

## Scheduled BAT variants

- `run_sensei_scheduled_loop.bat`: long unattended run mode. Start-button debug images are disabled, and constellation debug images are saved only when a mini-game solve is abandoned.
- `run_sensei_scheduled_loop_save-img.bat`: testing mode. Keeps the full debug image behavior.
