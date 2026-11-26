# Speech container

The speech container does speech recognition, voice activity detection and text to speech, using sherpa-onnx with the Parakeet, Whisper, Silero VAD models and Piper voices. The application service calls it over HTTP on the internal network (module `franca.speech_client`).

This folder is licensed under GPL-3.0-or-later (see `LICENSE`), because the Piper voices need piper_phonemize, which is built on espeak-ng, and espeak-ng is GPL-3.0-or-later. No code outside this folder imports from it. The rest of the app reaches the container over HTTP only.

The container will be built in story E12-001 and later stories.
