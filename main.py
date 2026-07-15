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
N_TRIALS = 15
TOTAL_DURATION = 4.0
RED_INTERVAL = 5.0
ASSUMED_FPS = 60.0
CROSS_SIZE = 20
CROSS_LINE_WIDTH = 3
IMAGE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.tif", "*.tiff")

RED_PROB_PER_FRAME = 1.0 / (RED_INTERVAL * ASSUMED_FPS)

RATE_OPTIONS = {
    "1 image / s": 1.0,
    "3 images / s": 3.0,
    "5.88 images / s": 5.88,
}

# ---------- Likert configuration ----------
LIKERT_QUESTION = "Avez-vous vu un visage ?"
LIKERT_OPTIONS = {
    "1": "1. Aucun visage du tout.",
    "2": "2. Pas certain",
    "3": "3. Visage mais avec détails manquants",
    "4": "4. Visage clair",
}
LIKERT_KEYS = list(LIKERT_OPTIONS.keys())  # ["1", "2", "3", "4"]

# ---------- Locate images (once) ----------
pictures_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), FOLDER_NAME)

if not os.path.isdir(pictures_dir):
    raise FileNotFoundError(f"Folder not found: {pictures_dir}")

image_files = []
for ext in IMAGE_EXTENSIONS:
    image_files.extend(glob.glob(os.path.join(pictures_dir, ext)))
    image_files.extend(glob.glob(os.path.join(pictures_dir, ext.upper())))
image_files = sorted(set(image_files))

if not image_files:
    raise RuntimeError(f"No images found in {pictures_dir}")

# ---------- Set up window (once, reused across trials) ----------
win = visual.Window(fullscr=True, color="black", units="pix")
stim = visual.ImageStim(win, image=None)

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

    while True:
        keys = event.getKeys(keyList=LIKERT_KEYS + ["escape"])
        if "escape" in keys:
            raise KeyboardInterrupt
        for k in keys:
            if k in LIKERT_KEYS:
                return k
        core.wait(0.005)  # avoid busy-spinning the CPU

# ---------- Clocks (reused) ----------
red_clock = core.Clock()
image_clock = core.Clock()
session_clock = core.Clock()

all_results = []  # one entry per completed trial

try:
    for trial in range(N_TRIALS):
        # ----- Randomize rate for THIS trial -----
        selected_label = random.choice(list(RATE_OPTIONS.keys()))
        rate = RATE_OPTIONS[selected_label]
        duration = 1.0 / rate  # seconds per image

        # ----- Per-trial state -----
        is_red = False
        fixation.lineColor = "blue"
        rt_data = []
        playlist = list(image_files)

        session_clock.reset()

        # Outer loop: keep cycling through images until 40 s elapse.
        while session_clock.getTime() < TOTAL_DURATION:
            random.shuffle(playlist)  # new random order for each full pass

            for img_path in playlist:
                if session_clock.getTime() >= TOTAL_DURATION:
                    break

                stim.image = img_path
                image_clock.reset()

                # Show this image until its slot ends OR the session ends.
                while (image_clock.getTime() < duration
                       and session_clock.getTime() < TOTAL_DURATION):

                    if not is_red and random.random() < RED_PROB_PER_FRAME:
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
        })

finally:
    win.close()

    print("\n===== SUMMARY (completed trials) =====")
    for r in all_results:
        rts = [round(x, 3) for x in r["rts"]]
        mean_rt = round(sum(r["rts"]) / len(r["rts"]), 3) if r["rts"] else None
        print(
            f"Trial {r['trial']:>2}: {r['label']:<16} "
            f"({r['duration']:.4f} s/img) | "
            f"session={r['session_time']:.2f}s | "
            f"RTs={rts} | mean={mean_rt} | "
            f"Likert={r['likert']} ({r['likert_label']})"
        )
    core.quit()