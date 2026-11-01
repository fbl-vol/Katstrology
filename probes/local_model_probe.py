"""Bounded CPU-only model/capture smoke test; no server or network calls.

Uses a local request file. This tiny model is for plumbing, not product selection.
"""

import argparse
from hashlib import file_digest
from importlib.metadata import version
import json
from pathlib import Path
import time
from uuid import uuid4

from llama_cpp import Llama

from capture_probe import Archive, run_turn


CONTEXT_TOKENS = 1024
REPLY_TOKENS = 128


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('request', type=Path)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--interrupt-after-chunks', type=int)
    args = parser.parse_args()
    if args.interrupt_after_chunks is not None and args.interrupt_after_chunks < 1:
        parser.error('--interrupt-after-chunks must be positive')

    request = args.request.read_text()
    prompt = (
        '<|im_start|>system\nUse only the supplied facts. Be concise; preserve uncertainty.'
        '<|im_end|>\n<|im_start|>user\n' + request +
        '<|im_end|>\n<|im_start|>assistant\n'
    )
    llm = Llama(model_path=str(args.model), n_ctx=CONTEXT_TOKENS, n_threads=2,
                n_threads_batch=2, n_batch=128, n_gpu_layers=0, seed=42, verbose=False)
    prompt_tokens = len(llm.tokenize(prompt.encode(), add_bos=True, special=True))
    if prompt_tokens + REPLY_TOKENS > CONTEXT_TOKENS:
        raise ValueError('Prompt exceeds budget; narrow it rather than silently truncate')

    archive = Archive(args.archive)
    turn_id = str(uuid4())
    delivered = []
    started = time.monotonic()

    def source():
        stream = llm.create_completion(prompt, max_tokens=REPLY_TOKENS, temperature=0,
                                       stop=['<|im_end|>'], stream=True)
        count = 0
        try:
            for chunk in stream:
                choice = chunk['choices'][0]
                if choice['text']:
                    yield {'kind': 'assistant_chunk', 'content': choice['text']}
                    count += 1
                    if args.interrupt_after_chunks and count >= args.interrupt_after_chunks:
                        yield {'kind': 'interrupted', 'reason': 'local cancellation probe'}
                        return
                if choice['finish_reason']:
                    if choice['finish_reason'] == 'stop':
                        yield {'kind': 'complete'}
                    else:
                        yield {'kind': 'interrupted', 'reason': choice['finish_reason']}
                    return
        finally:
            stream.close()

    try:
        # Archive the exact formatted model input for this low-level experiment.
        # A production adapter needs separate roles, request/settings and revisions.
        run_turn(archive, turn_id, prompt, source, delivered.append)
        saved = archive.replay(turn_id)[1:]
        if delivered != saved:
            raise AssertionError('Delivered content disagrees with the archive')
        def forbid_reinvocation():
            raise AssertionError('Retry invoked model')

        run_turn(archive, turn_id, prompt, forbid_reinvocation, lambda event: None)
        with args.model.open('rb') as model_file:
            model_hash = file_digest(model_file, 'sha256').hexdigest()
        print(json.dumps({
            'turn_id': turn_id, 'status': archive.status(turn_id),
            'llama_cpp_python': version('llama-cpp-python'),
            'model_sha256': model_hash,
            'prompt_tokens': prompt_tokens, 'context_tokens': CONTEXT_TOKENS,
            'reply_token_limit': REPLY_TOKENS, 'threads': 2,
            'elapsed_seconds': time.monotonic() - started,
            'delivered_matches_archive': True,
            'response': ''.join(event['content'] for event in saved if event['kind'] == 'assistant_chunk'),
            'terminal_event': saved[-1],
        }, indent=2))
    finally:
        archive.close()
        llm.close()


if __name__ == '__main__':
    main()
