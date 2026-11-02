"""Reuse only causally identical token-prefix states within one sample."""

POLICY = 'same_sample_exact_prefix_v1'


class ExactPrefixCache:
    def __init__(self):
        self.clear()

    def clear(self):
        self.ids, self.past = [], None

    def prepare(self, prompt_ids):
        # generate still receives the complete prompt/mask. Transformers slices
        # model inputs using cache_position; decoding/constraints see full IDs.
        kwargs = {'use_cache':True,'return_dict_in_generate':True}
        common = 0
        if self.past is not None:
            for old,new in zip(self.ids,prompt_ids):
                if old != new:
                    break
                common += 1
            common = min(common,len(prompt_ids)-1)
            if common <= 0:
                self.clear()
                common = 0
            else:
                self.past.crop(common)
                if self.past.get_seq_length() != common:
                    raise ValueError('Prefix cache length differs after crop')
                kwargs['past_key_values'] = self.past
        return kwargs, common

    def commit(self, sequence_ids, past):
        if past is None or not callable(getattr(past,'crop',None)):
            self.clear()
            return
        length = past.get_seq_length()
        if type(length) is not int or not 0 < length <= len(sequence_ids):
            raise ValueError('Generation cache length is inconsistent with its sequence')
        # HF typically has not forwarded the last emitted token (e.g. EOS).
        self.ids, self.past = list(sequence_ids[:length]), past
