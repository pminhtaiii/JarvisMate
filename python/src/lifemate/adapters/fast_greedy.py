"""Greedy constrained decoding that batches grammar-forced token stretches."""
from dataclasses import dataclass
import time

POLICY = 'greedy_forced_token_batch_v1'


def supported(model):
    config = getattr(model,'config',None)
    generation = getattr(model,'generation_config',None)
    if (not callable(model) or getattr(config,'model_type',None) != 'qwen3'
            or generation is None or getattr(model,'training',True)):
        return False
    # These processors can alter the greedy choice beyond the native prefix mask.
    neutral = {'min_length':(0,), 'min_new_tokens':(None,0), 'repetition_penalty':(1.,),
        'encoder_repetition_penalty':(1.,), 'no_repeat_ngram_size':(0,),
        'encoder_no_repeat_ngram_size':(0,), 'bad_words_ids':(None,), 'force_words_ids':(None,),
        'constraints':(None,), 'suppress_tokens':(None,), 'begin_suppress_tokens':(None,),
        'forced_bos_token_id':(None,), 'forced_eos_token_id':(None,), 'sequence_bias':(None,),
        'watermarking_config':(None,), 'guidance_scale':(None,1.),
        'exponential_decay_length_penalty':(None,), 'stop_strings':(None,), 'max_time':(None,)}
    return all(getattr(generation,key,values[0]) in values for key,values in neutral.items())


@dataclass
class GreedyResult:
    ids: list[int]
    past: object
    forward_calls: int
    forced_tokens: int


class TokenIDs(list):
    def tolist(self):
        return list(self)


def generate(model, prompt_ids, prefix, *, torch, device, eos_id, max_new_tokens, ends_at, past=None):
    ids = TokenIDs(prompt_ids)
    prompt_length = len(ids)
    calls, forced, logits_length, logits = 0, 0, -1, None
    vocab = model.config.vocab_size

    def forward():
        nonlocal past, calls, logits_length, logits
        seen = int(past.get_seq_length()) if past is not None else 0
        if not 0 <= seen < len(ids):
            raise ValueError('Invalid causal cache/input length')
        output = model(input_ids=torch.tensor([ids[seen:]],device=device),
            attention_mask=torch.ones((1,len(ids)),device=device,dtype=torch.long),
            past_key_values=past,use_cache=True,return_dict=True,logits_to_keep=1)
        logits = output.logits[0,-1].float()
        if not torch.isfinite(logits).all():
            raise ValueError('Nonfinite native generation logits')
        past = output.past_key_values
        calls += 1
        logits_length = len(ids)

    # Always evaluate the real prompt once, even if the grammar is deterministic.
    if time.monotonic() < ends_at:
        forward()
    while len(ids)-prompt_length < max_new_tokens and time.monotonic() < ends_at:
        allowed = list(prefix(0,ids))
        if not allowed or any(type(token) is not int or not 0 <= token < vocab for token in allowed):
            raise ValueError('Invalid native allowed-token set')
        if len(allowed) == 1:
            token = allowed[0]
            forced += 1
        else:
            if logits_length != len(ids):
                forward()
            if time.monotonic() >= ends_at:
                break
            candidates = torch.tensor(allowed,device=device)
            scores = logits.index_select(0,candidates)
            # Match full-vocabulary argmax's lowest-token-ID tie breaking.
            token = int(candidates.masked_fill(scores != scores.max(),vocab).min().item())
        ids.append(token)
        if token == eos_id:
            break
    return GreedyResult(list(ids),past,calls,forced)
