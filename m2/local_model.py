"""Optional local test-model adapter; hosted browser startup does not load its native binding."""

from pathlib import Path


DEFAULT_MODEL = Path('.local/models/qwen2.5-0.5b-instruct-q5_k_m.gguf')
LOCAL_CONTEXT_TOKENS = 2048  # Bounded natal context; not a hosted-model limit.


def model_at(path):
    from llama_cpp import Llama  # Only the explicitly selected local inference path needs this package.

    model = Llama(model_path=str(path), n_ctx=LOCAL_CONTEXT_TOKENS,
                  n_threads=2, n_threads_batch=2, n_batch=128,
                  n_gpu_layers=0, seed=42, verbose=False)
    model.context_limit = LOCAL_CONTEXT_TOKENS
    return model
