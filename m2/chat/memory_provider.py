"""One bounded tool-free request through the existing Responses parser/route."""
import json

from m2.chat.memory_analysis import INSTRUCTIONS, candidates
from m2.provider.model_capacity import Capacity, CatalogAdmission
from m2.provider.responses import ResponsesModel
from m2.provider.siwc import ProviderFailure


class _BackgroundAccess:
    """Reuse Responses framing while forbidding refresh and unbounded transport."""
    def __init__(self, bridge, binding):
        self.bridge, self.expected_binding = bridge, binding
        self.transport = self

    def access_bound(self, owner, binding):
        return self.bridge.background_access(owner, binding), binding

    def binding(self, owner):
        self.bridge.background_access(owner, self.expected_binding)
        return self.expected_binding

    def response_events(self, token, body):
        return self.bridge.transport.response_events(token, body, bounded=True)


def analyze(bridge, work, evidence):
    capacity = Capacity(**work['capacity'])
    admission = CatalogAdmission(work['owner_id'], work['model_slug'], work['account_binding'], capacity)
    model = ResponsesModel(_BackgroundAccess(bridge, admission.binding), admission.owner,
                           admission.slug, admission)
    prompt = json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))
    reserve = min(4096, capacity.max_output_tokens, max(1, capacity.context_window // 4))
    if len(model.tokenize(prompt + INSTRUCTIONS)) + reserve > capacity.context_window:
        raise ProviderFailure('background_capacity_unavailable')
    response = model.create_completion(prompt, instructions=INSTRUCTIONS, summary=True,
                                       max_output_tokens=reserve)
    text = ''
    try:
        for item in response:
            if item.get('choices'):
                text += item['choices'][0]['text']
                if len(text.encode()) > 16_384:
                    raise ProviderFailure('background_response_limit')
    finally:
        response.close()
        model.close()
    return candidates(evidence, text)
