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

The stock phrase is **"hey jarvis"**. For **"hey hullabaloo"**: train a model with the openWakeWord automatic
training notebook (linked from the openWakeWord GitHub README, "Training New Models"; it uses synthetic speech,
no recordings needed), export the `.onnx`, name it `hey_hullabaloo.onnx`, and put it in
`%APPDATA%\HolographicHullabaloo\wakeword\`. The app uses it instead of hey jarvis.

Sensitivity (0 to 1) maps to a detection threshold of 1.0 down to 0.1. Start at 0.5.
The pretrained models have a non-commercial license: fine for this project, check before selling anything.
