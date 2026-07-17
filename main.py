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
import random
from psychopy import visual, core, event

# ---------- Configuration ----------
SETS_ROOT = "Sets"
N_TRIALS = 15
TOTAL_DURATION = 40.0

# Mean interval (seconds) between red-cross onsets.
RED_INTERVAL = 5.0
# Minimum time the cross must remain blue before it is allowed to turn red again.
MIN_BLUE_DURATION = 1.0

CROSS_SIZE = 20
CROSS_LINE_WIDTH = 3

IMAGE_EXTENSIONS = ("png", "jpg", "jpeg")

COUNTDOWN_START = 3
COUNTDOWN_STEP = 1.0

DISPLAY_SIZE = (600, 600)
MEAN_IMAGE_NAME = "mean_selected_stimuli.png"
MEAN_EVERY_N = 4

RATE_OPTIONS = {
    "1 image / s":     (1.0,  "rate_1"),
    "3 images / s":    (3.0,  "rate_3"),
    "5.88 images / s": (5.88, "rate_5_88"),
}

# ---------- Likert configuration ----------
LIKERT_QUESTION = "Avez-vous vu un visage ?"
LIKERT_OPTIONS = {
    "1": "1. Aucun visage du tout.",
    "2": "2. Pas certain",
    "3": "3. Visage mais avec détails manquants",
    "4": "4. Visage clair",
}
LIKERT_KEYS = ["1", "2", "3", "4"]
NUMPAD_KEYS = ["num_1", "num_2", "num_3", "num_4"]

# Map numpad names back to canonical digits so callers get a clean '1'..'4'.
KEY_NORMALIZE = {f"num_{d}": d for d in "1234"}


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
    for trial in range(N_TRIALS):
        # ----- Randomize rate for THIS trial -----
        selected_label = random.choice(list(RATE_OPTIONS.keys()))
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
    core.quit()