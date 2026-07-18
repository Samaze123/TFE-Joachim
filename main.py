"""
Image slideshow (15 trials) with:
- Randomly chosen display rate (1, 3, or 5.88 images/s), re-randomized each trial
- Central fixation cross that randomly turns red; SPACE resets it to blue
- ESC to quit early

Hardened for cross-platform use (Windows / macOS / Linux):
- Red-cross onset is scheduled by wall-clock TIME (exponential inter-arrival),
  NOT by per-frame probability, so behavior is identical on any refresh rate.
- Case-insensitive-friendly image discovery for case-sensitive filesystems.
- Graceful window creation with backend fallback.
"""
import os
import glob
import json
import random
from psychopy import visual, core, event, gui
from datetime import datetime
try:
    import pandas as pd
    _HAVE_PANDAS = True
except ImportError:
    _HAVE_PANDAS = False
    import csv  # fallback

# ---------- Configuration loading ----------
CONFIG_FILENAME = "config.json"

_REQUIRED_KEYS = (
    "SETS_ROOT", "N_TRIALS", "TOTAL_DURATION",
    "RED_INTERVAL", "MIN_BLUE_DURATION",
    "CROSS_SIZE", "CROSS_LINE_WIDTH",
    "IMAGE_EXTENSIONS",
    "COUNTDOWN_START", "COUNTDOWN_STEP",
    "DISPLAY_SIZE", "MEAN_IMAGE_NAME", "MEAN_EVERY_N",
    "RATE_OPTIONS",
    "LIKERT_QUESTION", "LIKERT_OPTIONS",
)

_DESCRIPTIONS = {
    "SETS_ROOT":         "Root folder (relative to script) containing image set subfolders.",
    "N_TRIALS":          "Number of trials in the session (integer).",
    "TOTAL_DURATION":    "Duration of each trial in seconds.",
    "RED_INTERVAL":      "Mean seconds between red-cross onsets (Poisson).",
    "MIN_BLUE_DURATION": "Minimum seconds the cross stays blue before it may turn red.",
    "CROSS_SIZE":        "Half-length of the fixation cross arms, in pixels.",
    "CROSS_LINE_WIDTH":  "Line width of the fixation cross, in pixels.",
    "IMAGE_EXTENSIONS":  "JSON list of file extensions to load, e.g. [\"png\",\"jpg\"].",
    "COUNTDOWN_START":   "Countdown starting number before each trial.",
    "COUNTDOWN_STEP":    "Seconds each countdown number is shown.",
    "DISPLAY_SIZE":      "JSON [width, height] of images in pixels.",
    "MEAN_IMAGE_NAME":   "Filename of the special 'mean' image.",
    "MEAN_EVERY_N":      "Insert the mean image after every N regular images.",
    "RATE_OPTIONS":      "JSON object: label -> {rate, folder}.",
    "LIKERT_QUESTION":   "Question text shown on the Likert screen.",
    "LIKERT_OPTIONS":    "JSON object: key -> answer label.",
}
# ---------- Settings editor (startup) ----------
# Keys whose values are lists/dicts are edited as JSON text; scalars as-is.
_COMPLEX_KEYS = ("IMAGE_EXTENSIONS", "DISPLAY_SIZE", "RATE_OPTIONS", "LIKERT_OPTIONS")

def load_config(base_dir):
    """Load and validate config.json located next to this script."""
    path = os.path.join(base_dir, CONFIG_FILENAME)
    if not os.path.isfile(path):
        raise SystemExit(f"Configuration file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON in {path}: {e}")
    return validate_config(cfg, path)

# ---------- Config validation (reusable) ----------
def validate_config(cfg, source="config"):
    """Validate a config dict in-place. Raises SystemExit on failure."""
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise SystemExit(
            f"Missing required config key(s) in {source}: {', '.join(missing)}"
        )
    if not isinstance(cfg["RATE_OPTIONS"], dict) or not cfg["RATE_OPTIONS"]:
        raise SystemExit("RATE_OPTIONS must be a non-empty object.")
    for label, spec in cfg["RATE_OPTIONS"].items():
        if not isinstance(spec, dict) or "rate" not in spec or "folder" not in spec:
            raise SystemExit(
                f"RATE_OPTIONS['{label}'] must contain 'rate' and 'folder'."
            )
    return cfg



def _coerce_scalar(original, text):
    """Coerce edited text back to the original value's type."""
    text = text.strip()
    if isinstance(original, bool):
        return text.lower() in ("true", "1", "yes")
    if isinstance(original, int):
        return int(text)
    if isinstance(original, float):
        return float(text)
    return text  # str


def edit_config_dialog(cfg, base_dir):
    """Show an editable settings dialog for the whole config.

    Returns a (possibly updated) config dict. On Cancel, returns the original
    cfg unchanged (experiment proceeds with existing values).
    Complex values (lists/dicts) are edited as JSON.
    """
    dlg = gui.Dlg(title="Experiment Settings")
    dlg.addText("Review / edit configuration. Complex values are JSON.")

    field_kinds = {}  # key -> "scalar" | "json"
    for key in _REQUIRED_KEYS:
        value = cfg[key]
        desc = _DESCRIPTIONS.get(key, "")
        # Visible description embedded in the label; full text also as tooltip.
        label = f"{key}  —  {desc}" if desc else key
        if key in _COMPLEX_KEYS or isinstance(value, (list, dict)):
            dlg.addField(label, json.dumps(value, ensure_ascii=False), tip=desc)
            field_kinds[key] = "json"
        else:
            dlg.addField(label, value, tip=desc)
            field_kinds[key] = "scalar"

    dlg.addField("__save_to_disk__", True, label="Save changes to config.json")

    data = dlg.show()
    if not dlg.OK:
        print("Settings dialog cancelled; using existing config.")
        return cfg

    # data matches addField order: one entry per key, then the save flag.
    new_cfg = dict(cfg)
    errors = []
    for i, key in enumerate(_REQUIRED_KEYS):
        raw = data[i]
        try:
            if field_kinds[key] == "json":
                new_cfg[key] = json.loads(raw) if isinstance(raw, str) else raw
            else:
                new_cfg[key] = _coerce_scalar(cfg[key], str(raw))
        except (json.JSONDecodeError, ValueError) as e:
            errors.append(f"{key}: {e}")

    save_flag = bool(data[len(_REQUIRED_KEYS)])

    if errors:
        raise SystemExit("Invalid settings:\n  " + "\n  ".join(errors))

    # Re-validate structure before accepting.
    validate_config(new_cfg, "settings dialog")

    if save_flag:
        path = os.path.join(base_dir, CONFIG_FILENAME)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=2, ensure_ascii=False)
            print(f"Configuration saved to {path}")
        except OSError as e:
            print(f"Warning: could not save config ({e}); using values in-memory.")

    return new_cfg

base_dir = os.path.dirname(os.path.abspath(__file__))
_cfg = load_config(base_dir)
_cfg = edit_config_dialog(_cfg, base_dir)

SETS_ROOT          = _cfg["SETS_ROOT"]
N_TRIALS           = _cfg["N_TRIALS"]
TOTAL_DURATION     = _cfg["TOTAL_DURATION"]

RED_INTERVAL       = _cfg["RED_INTERVAL"]
MIN_BLUE_DURATION  = _cfg["MIN_BLUE_DURATION"]

CROSS_SIZE         = _cfg["CROSS_SIZE"]
CROSS_LINE_WIDTH   = _cfg["CROSS_LINE_WIDTH"]

IMAGE_EXTENSIONS   = tuple(_cfg["IMAGE_EXTENSIONS"])

COUNTDOWN_START    = _cfg["COUNTDOWN_START"]
COUNTDOWN_STEP     = _cfg["COUNTDOWN_STEP"]

DISPLAY_SIZE       = tuple(_cfg["DISPLAY_SIZE"])
MEAN_IMAGE_NAME    = _cfg["MEAN_IMAGE_NAME"]
MEAN_EVERY_N       = _cfg["MEAN_EVERY_N"]

RATE_OPTIONS = {
    label: (spec["rate"], spec["folder"])
    for label, spec in _cfg["RATE_OPTIONS"].items()
}

# --- Balanced trial schedule ---
# N_TRIALS is now interpreted as trials PER RATE. The total number of trials
# is N_TRIALS * (number of rates). Each rate appears exactly N_TRIALS times,
# and the overall presentation order is randomized.
TRIALS_PER_RATE = N_TRIALS
TRIAL_SCHEDULE = [label for label in RATE_OPTIONS.keys()
                  for _ in range(TRIALS_PER_RATE)]
random.shuffle(TRIAL_SCHEDULE)
TOTAL_TRIALS = len(TRIAL_SCHEDULE)   # == N_TRIALS * len(RATE_OPTIONS)

print(f"Trials per rate: {TRIALS_PER_RATE} | "
      f"Rates: {len(RATE_OPTIONS)} | Total trials: {TOTAL_TRIALS}")

LIKERT_QUESTION = _cfg["LIKERT_QUESTION"]
LIKERT_OPTIONS  = _cfg["LIKERT_OPTIONS"]

LIKERT_KEYS   = list(LIKERT_OPTIONS.keys())            # e.g. ["1","2","3","4"]
NUMPAD_KEYS   = [f"num_{k}" for k in LIKERT_KEYS]
KEY_NORMALIZE = {f"num_{k}": k for k in LIKERT_KEYS}


# ---------- Red-cross scheduler (time-based, monitor-independent) ----------
def schedule_next_red(now):
    """Return the absolute time (relative to the blue_clock) at which the cross
    should next turn red.

    Uses an exponential inter-arrival time with mean RED_INTERVAL, which gives
    a Poisson process of red onsets — the natural continuous-time analogue of
    the original per-frame Bernoulli model, but independent of frame rate.

    The MIN_BLUE_DURATION floor guarantees the cross stays blue long enough to
    be perceptible before it can turn red again.
    """
    delay = random.expovariate(1.0 / RED_INTERVAL)
    return now + max(MIN_BLUE_DURATION, delay)


# ---------- Locate images (once) ----------
base_dir = os.path.dirname(os.path.abspath(__file__))
sets_root = os.path.join(base_dir, SETS_ROOT)
if not os.path.isdir(sets_root):
    raise FileNotFoundError(f"Sets root not found: {sets_root}")


def _glob_case_insensitive(directory, ext):
    """Match files by extension regardless of case, robust on case-sensitive
    filesystems (Linux). Handles e.g. .png, .PNG, .Png."""
    patterns = {ext.lower(), ext.upper(), ext.capitalize()}
    matches = []
    for pat in patterns:
        matches.extend(glob.glob(os.path.join(directory, f"*.{pat}")))
    return matches


def load_set(folder_name):
    """Load one set folder -> (regular_images, mean_image_path).
    Raises if the folder or required images are missing."""
    set_dir = os.path.join(sets_root, folder_name)
    if not os.path.isdir(set_dir):
        raise FileNotFoundError(f"Set folder not found: {set_dir}")

    found = []
    for ext in IMAGE_EXTENSIONS:
        found.extend(_glob_case_insensitive(set_dir, ext))
    found = sorted(set(found))

    mean_path = None
    regulars = []
    for f in found:
        if os.path.basename(f).lower() == MEAN_IMAGE_NAME.lower():
            mean_path = f
        else:
            regulars.append(f)

    if not regulars:
        raise RuntimeError(f"No regular images in set '{folder_name}' ({set_dir})")
    if mean_path is None:
        raise RuntimeError(
            f"Required '{MEAN_IMAGE_NAME}' missing in set '{folder_name}' ({set_dir})"
        )
    return regulars, mean_path


# ---------- Pre-load every set once ----------
set_cache = {}  # folder_name -> (regulars, mean_path)
for _, (_, _folder) in RATE_OPTIONS.items():
    set_cache[_folder] = load_set(_folder)
    print(f"Loaded set '{_folder}': {len(set_cache[_folder][0])} regular images")


def build_display_sequence(regulars, mean_path, every_n):
    """Yield an endless sequence: `every_n` shuffled regular images, then
    the mean image, repeating. Regular images are reshuffled each full pass."""
    playlist = list(regulars)
    count = 0
    while True:
        random.shuffle(playlist)
        for img in playlist:
            yield img
            count += 1
            if count % every_n == 0:
                yield mean_path


# ---------- Participant info dialog ----------
def collect_participant_info():
    """Show a native dialog asking for the participant's name/username.

    Returns a non-empty string. Cancelling the dialog aborts the program
    cleanly. A blank entry falls back to a timestamped placeholder so the
    console summary always has an identifier.
    """
    dlg = gui.Dlg(title="Participant Information")
    dlg.addText("Please enter your name or username:")
    dlg.addField("Name / Username:", "")

    data = dlg.show()
    if not dlg.OK:  # user pressed Cancel or closed the dialog
        raise SystemExit("Experiment cancelled at participant-info dialog.")

    # data is a list matching the addField order.
    name = (data[0] if data else "").strip()
    if not name:
        name = "anonymous_" + core.getAbsTime().__str__()
    return name

# ---------- Set up window (once, reused across trials) ----------
def create_window():
    """Create the display window with a backend fallback for cross-platform
    robustness (glfw is often preferred on macOS; pyglet elsewhere)."""
    last_err = None
    for backend in ("pyglet", "glfw"):
        try:
            w = visual.Window(
                fullscr=True, color="black", units="pix", winType=backend
            )
            print(f"Window created with backend: {backend}")
            return w
        except Exception as e:  # noqa: BLE001 - we want to try the next backend
            last_err = e
            print(f"Backend '{backend}' failed: {e}")
    raise SystemExit(f"Could not open a window with any backend. Last error: {last_err}")


participant_name = collect_participant_info()
print(f"Participant: {participant_name}")


win = create_window()

# Informational only: timing no longer depends on this value.
try:
    measured_fps = win.getActualFrameRate(nIdentical=10, nMaxFrames=120)
    if measured_fps:
        print(f"Measured refresh rate: {measured_fps:.1f} Hz "
              f"(timing is frame-rate independent; this is informational)")
    else:
        print("Could not reliably measure refresh rate (not required).")
except Exception as e:  # noqa: BLE001
    print(f"Refresh-rate measurement skipped: {e}")

stim = visual.ImageStim(win, image=None, size=DISPLAY_SIZE, units="pix")

fixation = visual.ShapeStim(
    win,
    vertices=(
        (-CROSS_SIZE, 0), (CROSS_SIZE, 0),
        (0, 0),
        (0, -CROSS_SIZE), (0, CROSS_SIZE)
    ),
    lineColor="blue",
    lineWidth=CROSS_LINE_WIDTH,
    closeShape=False,
    units="pix",
    pos=(0, 0)
)

mouse = event.Mouse(win=win)

# Top-right corner button (units="pix", origin is center of screen)
win_w, win_h = win.size
close_btn = visual.Rect(
    win, width=40, height=40, units="pix",
    pos=(win_w/2 - 30, win_h/2 - 30),
    fillColor="darkred", lineColor="white", lineWidth=2,
)
close_x = visual.TextStim(
    win, text="X", color="white", height=24, bold=True,
    pos=close_btn.pos, units="pix",
)

def close_button_clicked():
    """Return True on a fresh left-click inside the close button (press edge)."""
    pressed, _ = mouse.getPressed(getTime=True)
    if pressed[0] and close_btn.contains(mouse):
        mouse.clickReset()  # avoid repeated triggers
        return True
    return False

# ---------- Likert stimuli (created once, reused) ----------
likert_title = visual.TextStim(
    win,
    text=LIKERT_QUESTION,
    color="white",
    height=32,
    pos=(0, 220),
    units="pix",
    wrapWidth=1000,
)

likert_body = visual.TextStim(
    win,
    text="\n\n".join(LIKERT_OPTIONS.values()) +
         "\n\n(Appuyez sur 1, 2, 3 ou 4)",
    color="white",
    height=26,
    pos=(0, -40),
    units="pix",
    wrapWidth=1100,
    alignText="left",
)

def export_results(results, participant):
    """Export trial results to an Excel workbook (two sheets).
    Falls back to CSV if pandas/openpyxl are unavailable."""
    if not results:
        print("No completed trials — nothing to export.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in participant)
    out_dir = os.path.join(base_dir, "results")
    os.makedirs(out_dir, exist_ok=True)

    # --- Sheet 1: one row per trial (summary) ---
    trial_rows = []
    for r in results:
        rts = r["rts"]
        trial_rows.append({
            "participant": participant,
            "trial": r["trial"],
            "rate_label": r["label"],
            "set_folder": r["set_folder"],
            "sec_per_image": round(r["duration"], 4),
            "session_time_s": round(r["session_time"], 3),
            "n_red_responses": len(rts),
            "mean_rt_s": round(sum(rts) / len(rts), 3) if rts else None,
            "min_rt_s": round(min(rts), 3) if rts else None,
            "max_rt_s": round(max(rts), 3) if rts else None,
            "rts_all_s": "; ".join(f"{x:.3f}" for x in rts),
            "likert": r["likert"],
            "likert_label": r["likert_label"],
        })

    # --- Sheet 2: one row per RT (long / tidy format) ---
    rt_rows = []
    for r in results:
        if r["rts"]:
            for i, rt in enumerate(r["rts"], start=1):
                rt_rows.append({
                    "participant": participant,
                    "trial": r["trial"],
                    "rate_label": r["label"],
                    "response_index": i,
                    "rt_s": round(rt, 3),
                    "likert": r["likert"],
                })
        else:
            rt_rows.append({
                "participant": participant,
                "trial": r["trial"],
                "rate_label": r["label"],
                "response_index": 0,
                "rt_s": None,
                "likert": r["likert"],
            })

    if _HAVE_PANDAS:
        path = os.path.join(out_dir, f"results_{safe_name}_{stamp}.xlsx")
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame(trial_rows).to_excel(writer, sheet_name="per_trial", index=False)
                pd.DataFrame(rt_rows).to_excel(writer, sheet_name="per_response", index=False)
            print(f"Results exported to Excel: {path}")
            return
        except Exception as e:  # e.g. openpyxl missing
            print(f"Excel export failed ({e}); falling back to CSV.")

    # CSV fallback (two files)
    p1 = os.path.join(out_dir, f"results_{safe_name}_{stamp}_per_trial.csv")
    p2 = os.path.join(out_dir, f"results_{safe_name}_{stamp}_per_response.csv")
    for path, rows in ((p1, trial_rows), (p2, rt_rows)):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(f"Results exported to CSV:\n  {p1}\n  {p2}")

def collect_likert_rating():
    """Display the Likert scale; return '1'..'4'. ESC or close button -> quit."""
    event.clearEvents()
    accepted = LIKERT_KEYS + NUMPAD_KEYS

    while True:
        likert_title.draw()
        likert_body.draw()
        close_btn.draw(); close_x.draw()
        win.flip()

        if close_button_clicked():
            raise KeyboardInterrupt

        keys = event.getKeys(keyList=accepted + ["escape"])
        if "escape" in keys:
            raise KeyboardInterrupt
        for k in keys:
            if k in accepted:
                return KEY_NORMALIZE.get(k, k)


# ---------- Countdown ----------
countdown_text = visual.TextStim(
    win,
    text="",
    color="white",
    height=120,
    pos=(0, 0),
    units="pix",
)


def run_countdown(start=COUNTDOWN_START, step=COUNTDOWN_STEP):
    """Display a centred numeric countdown before a trial.
    Honors ESC (raises KeyboardInterrupt)."""
    clock = core.Clock()
    event.clearEvents()
    for n in range(start, 0, -1):
        countdown_text.text = str(n)
        clock.reset()
        while clock.getTime() < step:
            if "escape" in event.getKeys(keyList=["escape"]):
                raise KeyboardInterrupt
            if close_button_clicked():
                raise KeyboardInterrupt
            countdown_text.draw()
            close_btn.draw(); close_x.draw()
            win.flip()
    win.flip()


# ---------- Clocks (reused) ----------
red_clock = core.Clock()       # measures reaction time once red appears
image_clock = core.Clock()     # per-image display timing
session_clock = core.Clock()   # overall 40 s trial timing
blue_clock = core.Clock()      # time since cross last became blue

all_results = []  # one entry per completed trial

try:
    for trial, selected_label in enumerate(TRIAL_SCHEDULE):
        # ----- Rate for THIS trial (pre-balanced & shuffled schedule) -----
        rate, set_folder = RATE_OPTIONS[selected_label]
        duration = 1.0 / rate  # seconds per image
        # Images for THIS trial come from the rate-specific set.
        trial_regulars, trial_mean = set_cache[set_folder]

        run_countdown()

        # ----- Per-trial state -----
        is_red = False
        fixation.lineColor = "blue"
        rt_data = []
        blue_clock.reset()
        session_clock.reset()

        # Schedule the first red onset by TIME (frame-rate independent).
        next_red_time = schedule_next_red(blue_clock.getTime())

        display_seq = build_display_sequence(trial_regulars, trial_mean, MEAN_EVERY_N)

        # Outer loop: keep cycling through images until 40 s elapse.
        for img_path in display_seq:
            if session_clock.getTime() >= TOTAL_DURATION:
                break

            stim.image = img_path
            image_clock.reset()

            # Show this image until its slot ends OR the session ends.
            while (image_clock.getTime() < duration
                   and session_clock.getTime() < TOTAL_DURATION):

                # --- Time-based red onset (replaces per-frame probability) ---
                # Turn red once the scheduled time is reached. blue_clock is
                # reset each time we return to blue, so next_red_time is always
                # expressed relative to the most recent blue onset.
                if not is_red and blue_clock.getTime() >= next_red_time:
                    is_red = True
                    fixation.lineColor = "red"
                    red_clock.reset()
                    event.clearEvents()

                keys = event.getKeys(keyList=["space", "escape"])

                if close_button_clicked():
                    raise KeyboardInterrupt
                if "escape" in keys:
                    raise KeyboardInterrupt
                if is_red and "space" in keys:
                    rt_data.append(red_clock.getTime())
                    is_red = False
                    fixation.lineColor = "blue"
                    blue_clock.reset()
                    # Schedule the NEXT red onset relative to this new blue start.
                    next_red_time = schedule_next_red(blue_clock.getTime())

                stim.draw()
                fixation.draw()
                close_btn.draw()
                close_x.draw()
                win.flip()

        # ----- Ask the Likert scale at the end of the trial -----
        rating_key = collect_likert_rating()
        rating_label = LIKERT_OPTIONS[rating_key]

        # ----- Record trial results -----
        all_results.append({
            "trial": trial + 1,
            "label": selected_label,
            "duration": duration,
            "session_time": session_clock.getTime(),
            "rts": rt_data,
            "likert": int(rating_key),
            "likert_label": rating_label,
            "set_folder": set_folder,
        })

except KeyboardInterrupt:
    print("\nExperiment aborted early by user (ESC).")

finally:
    win.close()

    print("\n===== SUMMARY (completed trials) =====")
    print(f"Participant: {participant_name}")
    for r in all_results:
        rts = [round(x, 3) for x in r["rts"]]
        mean_rt = round(sum(r["rts"]) / len(r["rts"]), 3) if r["rts"] else None
        print(
            f"Trial {r['trial']:>2}: {r['label']:<16} "
            f"Set Folder={r['set_folder']} "
            f"({r['duration']:.4f} s/img) | "
            f"session={r['session_time']:.2f}s | "
            f"RTs={rts} | mean={mean_rt} | "
            f"Likert={r['likert']} ({r['likert_label']}) |"
        )
    export_results(all_results, participant_name)
    core.quit()

