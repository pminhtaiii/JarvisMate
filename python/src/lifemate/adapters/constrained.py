"""Token-level action grammar. Tool argument semantics remain owned by ToolEnv."""
from __future__ import annotations

from importlib.metadata import version

from ..contracts import PipelineError


def argument_schemas(tool: dict) -> list[dict]:
    """Translate catalog structure; the simulator still validates values and references."""
    from copy import deepcopy

    def normalize(schema, required=False):
        result = deepcopy(schema)
        for key in ("description", "x-ref", "x-match"):
            result.pop(key, None)
        if result.get("type") == "object":
            required_keys = result.get("required", [])
            result["properties"] = {k: normalize(v, k in required_keys)
                                    for k, v in result.get("properties", {}).items()}
            result["additionalProperties"] = False
        if result.get("type") == "string" and required:
            result["minLength"] = max(1, result.get("minLength", 0))
        if result.get("type") == "array":
            result["items"] = normalize(result["items"])
            if required:
                result["minItems"] = max(1, result.get("minItems", 0))
        return result

    parameters = deepcopy(tool["parameters"])
    groups = parameters.pop("x-one-of", []) or [[]]
    branches = []
    for group in groups:
        branch = deepcopy(parameters)
        branch["required"] = list(dict.fromkeys(branch.get("required", []) + group))
        branches.append(normalize(branch))
    return branches


def action_parser(tools: list[dict], config):
    """Independent parser contexts per tool/alternative; canonical outer envelope.

    A generic anyOf object does not bind arbitrary arguments to the chosen tool.
    Literal prefixes also keep LMFE's config overrides away from envelope ordering.
    """
    import json
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.characterlevelparser import StringParser, UnionParser

    branches = [StringParser('{"action":"finish"}')]
    for tool in tools:
        prefix = '{"action":"call","name":' + json.dumps(tool["name"]) + ',"arguments":'
        for schema in argument_schemas(tool):
            # LMFE treats an empty properties dict as a free-form dictionary.
            # Explicitly encode the zero-parameter case rather than allowing junk keys.
            if not schema["properties"]:
                branches.append(StringParser(prefix + "{}}"))
            else:
                envelope = {"type": "object", "properties": {
                    "action": {"type": "string", "enum": ["call"]},
                    "name": {"type": "string", "enum": [tool["name"]]}, "arguments": schema},
                    "required": ["action", "name", "arguments"], "additionalProperties": False}
                branches.append(JsonSchemaParser(envelope, config=config))
    return UnionParser(branches)


class ActionConstraint:
    def __init__(self, tokenizer):
        try:
            from lmformatenforcer import CharacterLevelParserConfig
            from lmformatenforcer.integrations.transformers import (
                build_token_enforcer_tokenizer_data, build_transformers_prefix_allowed_tokens_fn)

            self.build_prefix = build_transformers_prefix_allowed_tokens_fn
            # Pin policy explicitly rather than accepting process environment overrides.
            self.config = CharacterLevelParserConfig(max_consecutive_whitespaces=2,
                                                     force_json_field_order=True,
                                                     max_json_array_length=16_384)
            self.tokenizer_data = build_token_enforcer_tokenizer_data(tokenizer)
            self.metadata = {"library": "lm-format-enforcer", "version": version("lm-format-enforcer"),
                             "schema": "lifemate-tool-arguments-v2", "strict_field_order": True,
                             "max_consecutive_whitespaces": 2, "unconstrained_fallback": False}
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot initialize required JSON constraints; install inference extra",
                                "model_load") from exc

    def prefix(self, tools: list[dict]):
        # A fresh parser/token-history per action, a shared tokenizer trie per model.
        from dataclasses import replace

        config = replace(self.config, alphabet=self.tokenizer_data.tokenizer_alphabet)
        return self.build_prefix(self.tokenizer_data, action_parser(tools, config))

    def schema_prefix(self, schema: dict):
        """Fresh parser for the optional, non-executing selection planning phase."""
        from dataclasses import replace
        from lmformatenforcer import JsonSchemaParser

        config = replace(self.config, alphabet=self.tokenizer_data.tokenizer_alphabet)
        return self.build_prefix(self.tokenizer_data, JsonSchemaParser(schema, config=config))
