"""
Image slideshow (15 trials) with:
- Randomly chosen display rate (1, 3, or 5.88 images/s), re-randomized each trial
- Central fixation cross that randomly turns red; SPACE resets it to blue
- ESC to quit early
"""

import os
import glob
import random
from psychopy import visual, core, event

# ---------- Configuration ----------
FOLDER_NAME = "Pictures"
SETS_ROOT = "Sets"
N_TRIALS = 15
TOTAL_DURATION = 40.0

RED_INTERVAL = 5.0
ASSUMED_FPS = 60.0
RED_PROB_PER_FRAME = 1.0 / (RED_INTERVAL * ASSUMED_FPS)
MIN_BLUE_DURATION = 1.0

CROSS_SIZE = 20
CROSS_LINE_WIDTH = 3

IMAGE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg")

COUNTDOWN_START = 3
COUNTDOWN_STEP = 1.0 

RED_PROB_PER_FRAME = 1.0 / (RED_INTERVAL * ASSUMED_FPS)

DISPLAY_SIZE = (200, 200)
MEAN_IMAGE_NAME = "mean_selected_stimuli.png"
MEAN_EVERY_N = 4

RATE_OPTIONS = {
    "1 image / s":     (1.0,  "rate_1"),
    # "3 images / s":    (3.0,  "rate_3"),
    # "5.88 images / s": (5.88, "rate_5_88"),
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

# ---------- Locate images (once) ----------
base_dir = os.path.dirname(os.path.abspath(__file__))
sets_root = os.path.join(base_dir, SETS_ROOT)
if not os.path.isdir(sets_root):
    raise FileNotFoundError(f"Sets root not found: {sets_root}")


def load_set(folder_name):
    """Load one set folder → (regular_images, mean_image_path).
    Raises if the folder or required images are missing."""
    set_dir = os.path.join(sets_root, folder_name)
    if not os.path.isdir(set_dir):
        raise FileNotFoundError(f"Set folder not found: {set_dir}")

    found = []
    for ext in IMAGE_EXTENSIONS:
        found.extend(glob.glob(os.path.join(set_dir, ext)))
        found.extend(glob.glob(os.path.join(set_dir, ext.upper())))
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
set_cache = {}   # folder_name -> (regulars, mean_path)
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
win = visual.Window(fullscr=True, color="black", units="pix")
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
    """Display the Likert scale and return the pressed key ('1'..'4').
    Raises KeyboardInterrupt if ESC is pressed."""
    event.clearEvents()
    likert_title.draw()
    likert_body.draw()
    win.flip()

    accepted = LIKERT_KEYS + NUMPAD_KEYS

    while True:
        keys = event.waitKeys(keyList=accepted + ["escape"])
        if "escape" in keys:
            raise KeyboardInterrupt
        for k in keys:
            if k in accepted:   
                return KEY_NORMALIZE.get(k, k)
            
# ----------Countdown -----------------
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
            countdown_text.draw()
            win.flip()
    win.flip() 

# ---------- Clocks (reused) ----------
red_clock = core.Clock()
image_clock = core.Clock()
session_clock = core.Clock()
blue_clock = core.Clock()

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

                if (not is_red and blue_clock.getTime() >= MIN_BLUE_DURATION
                        and random.random() < RED_PROB_PER_FRAME):
                    is_red = True
                    fixation.lineColor = "red"
                    red_clock.reset()
                    event.clearEvents()

                keys = event.getKeys(keyList=["space", "escape"])
                if "escape" in keys:
                    raise KeyboardInterrupt
                if is_red and "space" in keys:
                    rt_data.append(red_clock.getTime())
                    is_red = False
                    fixation.lineColor = "blue"
                    blue_clock.reset()

                stim.draw()
                fixation.draw()
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

finally:
    win.close()

    print("\n===== SUMMARY (completed trials) =====")
    for r in all_results:
        rts = [round(x, 3) for x in r["rts"]]
        mean_rt = round(sum(r["rts"]) / len(r["rts"]), 3) if r["rts"] else None
        print(
            f"Trial {r['trial']:>2}: {r['label']:<16} "
            f"Set Folder={r['set_folder']}"
            f"({r['duration']:.4f} s/img) | "
            f"session={r['session_time']:.2f}s | "
            f"RTs={rts} | mean={mean_rt} | "
            f"Likert={r['likert']} ({r['likert_label']}) | "
        )
    core.quit()