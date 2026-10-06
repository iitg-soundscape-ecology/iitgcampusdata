import subprocess
import datetime
import os
import time
import csv
import threading
import queue

import librosa
import numpy as np
import joblib

# -------------------------------------------------
# BASE PATH
# -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------
# OUTPUT PATH CONFIGURATION
# -------------------------------------------------
PRIMARY_DIR = "/media/rpi/AranyaShruti/Audio_Recordings"
FALLBACK_DIR = "/media/rpi/soundscape/Audio_Recordings"

if os.path.exists(PRIMARY_DIR):
    OUTPUT_DIR = PRIMARY_DIR
else:
    print(f"[WARNING] External SSD not detected at {PRIMARY_DIR}. Falling Back to local storage.")
    OUTPUT_DIR = FALLBACK_DIR

CSV_LOG = os.path.join(OUTPUT_DIR, "sound_log.csv")

MODEL_PATH = os.path.join(BASE_DIR, "sound_classifier.pkl")

GAIN_DB = 20
RECORD_INTERVAL = 5 # Default if config file is missing
NORMALIZE = True

AUDIO_DEVICE = "plughw:3,0"

CLASS_NAMES = ["human", "anthropogenic", "animal"]

CONFIG_PATH = "/home/rpi/Desktop/Working code/data_mule_config.json"

import json

def load_mule_config():
    defaults = {
        "duration": RECORD_INTERVAL,
        "pause": 20
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                dur = data.get("duration", RECORD_INTERVAL)
                pause = data.get("pause", 20)
                return int(dur), int(pause)
        except Exception as e:
            print("[WARNING] Failed to load dynamic config, using default values:", e)
    return defaults["duration"], defaults["pause"]

# -------------------------------------------------
# LOAD MODEL
# -------------------------------------------------
print("[INFO] Loading sound classification model...")
model = joblib.load(MODEL_PATH)
print("[OK] Model loaded successfully")

# -------------------------------------------------
# QUEUE
# -------------------------------------------------
audio_queue = queue.Queue(maxsize=100)

# -------------------------------------------------
# FEATURE EXTRACTION
# -------------------------------------------------
def extract_features(audio_path):

    y, sr = librosa.load(
        audio_path,
        sr=22050,
        mono=True
    )

    mfcc = librosa.feature.mfcc(
        y=y,
        sr=sr,
        n_mfcc=20
    )

    features = np.hstack(
        (
            np.mean(mfcc, axis=1),
            np.std(mfcc, axis=1)
        )
    )

    return features


# -------------------------------------------------
# CLASSIFICATION
# -------------------------------------------------
def classify_audio(wav_path):

    features = extract_features(wav_path)

    probs = model.predict_proba([features])[0]

    class_id = np.argmax(probs)

    return (
        CLASS_NAMES[class_id],
        float(probs[class_id])
    )


# -------------------------------------------------
# CSV LOGGER
# -------------------------------------------------
def log_to_csv(
    timestamp,
    audio_file,
    label,
    confidence
):

    os.makedirs(
        os.path.dirname(CSV_LOG),
        exist_ok=True
    )

    file_exists = os.path.isfile(CSV_LOG)

    with open(
        CSV_LOG,
        "a",
        newline=""
    ) as f:

        writer = csv.writer(f)

        if not file_exists:

            writer.writerow([
                "timestamp",
                "audio_file",
                "class",
                "confidence"
            ])

        writer.writerow([
            timestamp,
            audio_file,
            label,
            round(confidence, 3)
        ])


# -------------------------------------------------
# AUDIO DEVICE CHECK
# -------------------------------------------------
def wait_for_audio_device(timeout=60):

    print(
        "[INFO] Waiting for USB microphone..."
    )

    for _ in range(timeout):

        try:

            r = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True
            )

            if "card 3" in r.stdout:

                print(
                    "[OK] Audio device detected"
                )

                return True

        except Exception:
            pass

        time.sleep(1)

    print(
        "[ERROR] Audio device not detected"
    )

    return False


# -------------------------------------------------
# RECORD AUDIO
# -------------------------------------------------
def record_audio(duration):

    ts = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    wav_file = os.path.join(
        OUTPUT_DIR,
        f"{ts}.wav"
    )

    effects = [
        "gain",
        str(GAIN_DB)
    ]

    if NORMALIZE:
        effects.append("norm")

    record_cmd = [
        "sox",
        "-t",
        "alsa",
        "-D",
        AUDIO_DEVICE,
        "-c",
        "1",
        "-b",
        "16",
        "-r",
        "40000",
        wav_file,
        "trim",
        "0",
        str(duration)
    ] + effects

    try:

        subprocess.run(
            record_cmd,
            check=True
        )

        return wav_file

    except subprocess.CalledProcessError as e:

        print(
            "[ERROR] Recording failed:",
            e
        )

        return None


# -------------------------------------------------
# RECORDER THREAD
# -------------------------------------------------
def recorder_thread():

    print(
        "[INFO] Recorder thread started"
    )

    while True:

        duration, pause_val = load_mule_config()
        wav_file = record_audio(duration)

        if wav_file:

            try:

                audio_queue.put(
                    wav_file,
                    timeout=10
                )

                print(
                    f"[RECORDED] "
                    f"{os.path.basename(wav_file)}"
                )

            except queue.Full:

                print(
                    "[WARNING] Queue full. "
                    "Dropping file."
                )

        if pause_val > 0:
            time.sleep(pause_val)


# -------------------------------------------------
# PROCESSOR THREAD
# -------------------------------------------------
def processor_thread():

    print(
        "[INFO] Classifier thread started"
    )

    while True:

        wav_file = audio_queue.get()

        try:

            label, confidence = classify_audio(
                wav_file
            )

            timestamp = (
                datetime.datetime.now()
                .strftime("%Y-%m-%d %H:%M:%S")
            )

            print(
                f"[CLASS] "
                f"{label} "
                f"({confidence:.2f})"
            )

            log_to_csv(
                timestamp,
                os.path.basename(
                    wav_file
                ),
                label,
                confidence
            )

        except Exception as e:

            print(
                "[ERROR] Classification failed:",
                e
            )

        finally:

            audio_queue.task_done()


# -------------------------------------------------
# MAIN
# -------------------------------------------------
if __name__ == "__main__":

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    if not wait_for_audio_device():
        raise SystemExit(1)

    recorder = threading.Thread(
        target=recorder_thread,
        daemon=True
    )

    processor = threading.Thread(
        target=processor_thread,
        daemon=True
    )

    recorder.start()
    processor.start()

    print(
        "\n[INFO] Continuous sound monitoring started"
    )

    try:

        while True:
            time.sleep(10)

    except KeyboardInterrupt:

        print(
            "\n[INFO] Stopped by user"
        )