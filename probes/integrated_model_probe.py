"""Synthetic real-CPU-model + Swiss tool/capture/context smoke, no private input."""

import argparse
from hashlib import file_digest
from importlib.metadata import version
import json
from pathlib import Path
from uuid import uuid4

from llama_cpp import Llama
import swisseph as swe

from capture_probe import Archive, run_turn
from conversation_probe import run_calculation_turn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    swe.set_ephe_path(str((Path(__file__).resolve().parents[1] / '.local/ephe').resolve()))
    model = Llama(model_path=str(args.model), n_ctx=1024, n_threads=2,
                  n_threads_batch=2, n_batch=128, n_gpu_layers=0, seed=42, verbose=False)
    archive = Archive(args.archive)
    prompts = []

    class ObservedModel:
        def tokenize(self, *values, **settings):
            return model.tokenize(*values, **settings)

        def create_completion(self, prompt, **settings):
            prompts.append(prompt)
            return model.create_completion(prompt, **settings)

    observed = ObservedModel()
    try:
        root = str(uuid4())
        parent = None
        # Explicit synthetic revisions: an abandoned response and a selected edit.
        for i in range(16):
            turn_id = str(uuid4()) if i else root
            text = f'Synthetic archive item {i}: ' + 'old context ' * 24
            run_turn(archive, turn_id, text,
                     lambda i=i: iter([{'kind': 'assistant_chunk', 'content': f'Synthetic reply {i} ' + 'history ' * 24},
                                       {'kind': 'complete'}]), lambda _: None, parent_id=parent)
            parent = turn_id
        abandoned = str(uuid4())
        run_turn(archive, abandoned, 'ABANDONED_BRANCH',
                 lambda: iter([{'kind': 'assistant_chunk', 'content': 'Do not use this branch'},
                               {'kind': 'complete'}]), lambda _: None, parent_id=parent)
        selected = str(uuid4())
        run_turn(archive, selected, 'SELECTED_EDIT',
                 lambda: iter([{'kind': 'assistant_chunk', 'content': 'Selected branch'},
                               {'kind': 'complete'}]), lambda _: None, parent_id=parent)

        results = []
        for name, interrupt_after in [('complete', None), ('cancelled', 5)]:
            turn_id = str(uuid4())
            delivered = []
            request = 'solar longitude at 2024-03-20T03:06:00+00:00'
            run_calculation_turn(archive, turn_id, selected, request, observed,
                                 delivered.append, interrupt_after=interrupt_after)
            events = archive.replay(turn_id)
            assert delivered == events[1:]
            assert archive.replay(abandoned)[0]['content'] == 'ABANDONED_BRANCH'
            assert archive.ancestry(selected)[-1] == selected
            assert 'SELECTED_EDIT' in prompts[-1] and 'ABANDONED_BRANCH' not in prompts[-1]
            assert 'Synthetic archive item 0:' not in prompts[-1]
            before = len(events)
            run_calculation_turn(archive, turn_id, selected, request, observed, lambda _: None)
            assert len(archive.replay(turn_id)) == before
            results.append({
                'name': name, 'status': archive.status(turn_id),
                'budget': next(e['budget'] for e in events if e['kind'] == 'context'),
                'longitude_degrees': next(e['result']['longitude_degrees'] for e in events
                                          if e['kind'] == 'tool_result'),
                'delivered_matches_archive': True, 'replay_event_count': len(archive.replay(turn_id)),
                'max_committed_chunk_characters': max((len(e['content']) for e in events
                                                      if e['kind'] == 'assistant_chunk'), default=0),
                'response': ''.join(e['content'] for e in events if e['kind'] == 'assistant_chunk'),
            })
        with args.model.open('rb') as file:
            digest = file_digest(file, 'sha256').hexdigest()
        print(json.dumps({'runs': results, 'python_model_binding': version('llama-cpp-python'),
                          'swiss_engine': swe.version, 'model_sha256': digest,
                          'original_turns_retained': archive.db.execute('SELECT COUNT(*) FROM turns').fetchone()[0],
                          'selected_prompt_excludes_abandoned_and_oldest': True,
                          'model_context_tokens': 1024, 'reply_token_limit': 128, 'cpu_threads': 2}, indent=2))
    finally:
        archive.close()
        model.close()


if __name__ == '__main__':
    main()
