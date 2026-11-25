# Wake word (openWakeWord)

Runs fully on the laptop, no account. (Picovoice Porcupine was tried on Nov 22 and dropped: its free tier ended
June 30, 2026; only a 7-day enterprise trial is left.)

## Mic modes (Home, or Settings, Voice and wake)
- **Off**: the microphone is closed. Push-to-talk is refused.
- **Hotkey only** (default): the mic opens only while push-to-talk is held (Ctrl+Space, or Hold to talk), then closes.
- **Wake word**: the mic is open, but audio goes only to the wake word model and is thrown away until it hears the
  wake word. Then it captures one sentence, replies, and goes back to waiting. Nothing said within 8 s: back to waiting.

## Models
openWakeWord does not ship its models inside the pip package (that is why the old build failed with
"hey_jarvis_v0.1.onnx ... File doesn't exist"). The first time Wake word is switched on, the app downloads
melspectrogram.onnx, embedding_model.onnx and hey_jarvis_v0.1.onnx (a few MB, from the openWakeWord GitHub
releases) into `%APPDATA%\HolographicHullabaloo\wakeword\oww\`. After that it works offline.
Status shows in Settings, Voice and wake, and on Home.

The stock phrase is **"hey jarvis"**.

## Making "hey hullabaloo" (step by step)
The app already loads any custom model you drop in the wake word folder; you just have to train one.
openWakeWord's README links a Google Colab notebook ("Training New Models", the "Google Colab" link) that makes a
basic model in under an hour. It makes its own training clips with synthetic speech, so you don't record anything.

1. Open the openWakeWord GitHub page, scroll to "Training New Models" and open the Google Colab link.
2. In Colab: Runtime, Change runtime type, pick a GPU (the free T4 is fine).
3. Enter the phrase where the notebook asks for the wake word. Spell it how it sounds, so the speech generator says it
   right; try `hey hullabaloo` first, and `hey hulla baloo` if the first model misses it a lot.
4. Run all cells and wait. Keep the tab open, Colab stops if you close it.
5. Download the `.onnx` file it makes at the end. Rename it `hey_hullabaloo.onnx`.
6. In the app: Settings, Voice and wake, Custom wake word, **Open folder**. Put the file in that folder
   (`%APPDATA%\HolographicHullabaloo\wakeword\`). Keep only one `.onnx` there, the app takes the first one.
7. Switch the mic to Off and back to Hotkey + wake word. Home should now say "Say hey hullabaloo".
8. Test from across the room. Too many false wakes: lower the sensitivity. Misses: raise it, or retrain with
   the other spelling.

Write down in the journal that the model was trained with the openWakeWord notebook.

Sensitivity (0 to 1) maps to a detection threshold of 1.0 down to 0.1. Start at 0.5.
The pretrained models have a non-commercial license: fine for this project, check before selling anything.
