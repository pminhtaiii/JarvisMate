"""Separate CPU backend composition check; no tokenizer weights or GPU."""
import os
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get("LIFEMATE_LLM_CPU_BACKEND") == "1", "explicit CPU LMFE composition scope")
class BackendCompositionTests(unittest.TestCase):
    def test_immutable_compositions_compute_character_sets_once(self):
        from unittest.mock import patch
        from lmformatenforcer import CharacterLevelParserConfig
        from lifemate.adapters.qwen_native import native_decoder_parser
        tool={'name':'tasks.demo','parameters':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}
        parser=native_decoder_parser([tool],CharacterLevelParserConfig())
        sequence=parser.parsers[1]
        with patch.object(sequence.parsers[0],'get_allowed_characters',wraps=sequence.parsers[0].get_allowed_characters) as chars:
            first=sequence.get_allowed_characters()
            self.assertEqual(sequence.get_allowed_characters(),first)
            self.assertEqual(chars.call_count,1)
        with patch.object(sequence,'get_allowed_characters',wraps=sequence.get_allowed_characters) as chars:
            first=parser.get_allowed_characters()
            self.assertEqual(parser.get_allowed_characters(),first)
            self.assertEqual(chars.call_count,1)

    def test_optimized_composition_has_the_stock_character_language(self):
        from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser
        from lmformatenforcer.characterlevelparser import StringParser, SequenceParser, UnionParser
        from lifemate.adapters.qwen_native import (FINAL_CONTENT, CALL_SUFFIX_TEXT, call_prefix_text,
            call_completion_text, decoder_argument_schemas, native_decoder_parser)
        from lifemate.llm_training.data import load_catalog
        _, specs = load_catalog(Path(__file__).resolve().parents[2]/"tools/train_tools_catalog.json")
        tools = [specs[n] for n in ("ewallet.transfer", "alarm.list")]
        cfg = CharacterLevelParserConfig(max_consecutive_whitespaces=2, max_json_array_length=16384)
        def stock():
            branches = [StringParser(FINAL_CONTENT)]
            for tool in tools:
                prefix = call_prefix_text(tool["name"])
                for schema in decoder_argument_schemas(tool):
                    branches.append(SequenceParser([StringParser(prefix), JsonSchemaParser(schema, config=cfg),
                        StringParser(CALL_SUFFIX_TEXT)]) if schema["properties"] else StringParser(prefix+"{}"+CALL_SUFFIX_TEXT))
            return UnionParser(branches)
        texts = [FINAL_CONTENT, call_completion_text("alarm.list", {}),
                 call_completion_text("ewallet.transfer", {"phone": "0912345678", "amount": 120000}),
                 call_completion_text("ewallet.transfer", {"contact_id": "c_1", "phone": "0912345678", "amount": 120000}),
                 call_completion_text("ewallet.transfer", {"contact_id": "c_1", "amount": 120000, "note": "<tool_call> hi </tool_call>"}),
                 call_completion_text("ewallet.transfer", {"amount": 1}), "invalid", FINAL_CONTENT+" extra"]
        for text in texts:
            a, b = native_decoder_parser(tools, cfg), stock()
            for char in text:
                self.assertEqual(set(a.get_allowed_characters()), set(b.get_allowed_characters()))
                self.assertEqual(a.can_end(), b.can_end())
                if char not in a.get_allowed_characters():
                    break
                a, b = a.add_character(char), b.add_character(char)
            else:
                self.assertEqual(a.can_end(), b.can_end())


if __name__ == "__main__":
    unittest.main()
