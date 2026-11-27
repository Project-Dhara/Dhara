# Third-party notices (Dhara Desktop)

## Ollama

Ollama is an optional local LLM runtime bundled for Windows (standalone CLI zip).

- Source: https://github.com/ollama/ollama
- Website: https://ollama.com
- License: MIT (see the upstream repository `LICENSE`)
- Artifact: `ollama-windows-amd64.zip` from GitHub Releases (pinned by `scripts/fetch-ollama.ps1`)

Dhara may start the bundled `ollama serve` when you opt into a local model in Settings.
Model weights such as `gemma3:1b` are **not** redistributed with the installer; they are
downloaded on first use via Ollama’s pull API into `%LOCALAPPDATA%\Dhara\ollama`.
Builds with `-SkipOllama` omit the runtime.

## google/embeddinggemma-300m

EmbeddingGemma is provided by Google and distributed under the **Gemma** license terms.

- Source: https://huggingface.co/google/embeddinggemma-300m
- License: Gemma (see the model card and Google’s Gemma terms of use)
- Access is gated on Hugging Face: builders must accept the license and use an `HF_TOKEN` when running `prepare-backend.ps1`.

Dhara Desktop bundles model weights under `resources/win-x64/models/embeddinggemma-300m/` for offline NCO occupation matching. Builds with `-SkipEmbeddings` omit this model.

Please review Google’s Gemma license before redistributing installers that include these weights:
https://ai.google.dev/gemma/terms
