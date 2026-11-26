# Third-party notices (Dhara Desktop)

## google/embeddinggemma-300m

EmbeddingGemma is provided by Google and distributed under the **Gemma** license terms.

- Source: https://huggingface.co/google/embeddinggemma-300m
- License: Gemma (see the model card and Google’s Gemma terms of use)
- Access is gated on Hugging Face: builders must accept the license and use an `HF_TOKEN` when running `prepare-backend.ps1`.

Dhara Desktop bundles model weights under `resources/win-x64/models/embeddinggemma-300m/` for offline NCO occupation matching. Builds with `-SkipEmbeddings` omit this model.

Please review Google’s Gemma license before redistributing installers that include these weights:
https://ai.google.dev/gemma/terms
