import hashlib
import json
from pathlib import Path
import time
import unittest

from lifemate import skills
from lifemate.skills import (
    SkillLibraryError,
    load_library,
    retrieve,
)


ROOT = Path(__file__).resolve().parents[2]


def _catalog(split):
    path = ROOT / "tools" / f"{split}_tools_catalog.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    tools = {
        tool["name"]: tool
        for app in value["apps"]
        for tool in app["tools"]
    }
    return path, value, tools


class SkillLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = load_library()
        _, _, train = _catalog("train")
        _, _, public = _catalog("public_test")
        cls.train_tools = frozenset(train)
        cls.public_tools = frozenset(public)
        cls.all_tools = cls.train_tools | cls.public_tools

    def test_versioned_inventory_and_evidence_gate(self):
        library = self.library
        self.assertTrue(library.version)
        self.assertEqual(len(library.parents), 24)
        self.assertEqual(len(library.branches), 80)
        self.assertEqual(
            {evidence: sum(branch.evidence == evidence for branch in library.branches)
             for evidence in "ESH"},
            {"E": 63, "S": 13, "H": 4},
        )
        self.assertEqual(set(library.shared), {f"C{i:02d}" for i in range(1, 7)})
        self.assertEqual(library.runtime_evidence_policy, "E")
        self.assertEqual(
            {branch.branch_id for branch in library.branches if branch.evidence == "H"},
            {"S15.B01", "S15.B02", "S23.B01", "S23.B02"},
        )

    def test_catalog_fingerprints_and_parameter_references_match_bundled_catalogs(self):
        for split in ("train", "public_test"):
            path, catalog, tools = _catalog(split)
            fingerprint = self.library.catalog_fingerprints[split]
            self.assertEqual(fingerprint.schema_version, catalog["schema_version"])
            self.assertEqual(fingerprint.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
            for branch in self.library.branches:
                for name, splits in branch.catalog_splits.items():
                    if split not in splits:
                        continue
                    self.assertIn(name, tools)
                for parameter in branch.parameters:
                    if split not in branch.catalog_splits[parameter.tool]:
                        continue
                    schema = tools[parameter.tool]["parameters"]
                    self.assertEqual(list(parameter.required), schema.get("required", []))
                    self.assertEqual(
                        [list(group) for group in parameter.x_one_of],
                        schema.get("x-one-of", []),
                    )
                    self.assertTrue(set(parameter.optional) <=
                                    set(schema["properties"]) - set(schema.get("required", [])))

    def test_library_schema_rejects_unknown_action_and_argument(self):
        raw = skills.resources.files("lifemate").joinpath("skill_library.json").read_bytes()
        payload = json.loads(raw)
        branch = next(item for item in payload["branches"] if item["branch_id"] == "S11.B02")
        tool = branch["action_groups"][0][0]
        branch["action_groups"][0][0] = "invented.cancel"
        branch["parameters"][0]["tool"] = "invented.cancel"
        branch["catalog_splits"]["invented.cancel"] = branch["catalog_splits"].pop(tool)
        with self.assertRaises(SkillLibraryError):
            skills._parse_library(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        payload = json.loads(raw)
        branch = next(item for item in payload["branches"] if item["branch_id"] == "S11.B02")
        branch["parameters"][0]["required"] = ["invented_argument"]
        with self.assertRaises(SkillLibraryError):
            skills._parse_library(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        payload = json.loads(raw)
        branch = next(item for item in payload["branches"] if item["branch_id"] == "S11.B02")
        branch["conditional_dependencies"][0]["input_alternatives"] = [["invented_argument"]]
        with self.assertRaises(SkillLibraryError):
            skills._parse_library(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def test_library_schema_rejects_duplicate_keys_and_evidence_policy_changes(self):
        with self.assertRaises(SkillLibraryError):
            skills._parse_library(b'{"version":"a","version":"b"}')
        raw = skills.resources.files("lifemate").joinpath("skill_library.json").read_bytes()
        payload = json.loads(raw)
        payload["runtime_evidence_policy"] = "S"
        with self.assertRaises(SkillLibraryError):
            skills._parse_library(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class SkillRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = load_library()
        _, _, train = _catalog("train")
        _, _, public = _catalog("public_test")
        cls.train_tools = frozenset(train)
        cls.public_tools = frozenset(public)
        cls.all_tools = cls.train_tools | cls.public_tools

    def ids(self, request, tools=None, history=()):
        tools = self.all_tools if tools is None else tools
        return {item.branch_id for item in retrieve(request, history, tools, self.library)}

    def test_evidence_gate_negation_and_conditional_request(self):
        self.assertEqual(self.ids("Hủy gói xem phim"), {"S11.B02"})
        self.assertEqual(self.ids("Đặt xe công nghệ đến sân bay"), set())  # S evidence
        self.assertEqual(self.ids("Dựa công thức mua nguyên liệu còn thiếu"), set())  # H evidence
        self.assertEqual(self.ids("không hủy gói, chỉ xem điểm"), set())
        self.assertEqual(self.ids("đừng gửi, chỉ dịch"), set())
        # The completed cancellation is not repeated while the new music request remains actionable.
        self.assertEqual(
            self.ids("Tôi đã hủy gói xem phim rồi, mở playlist"),
            {"S18.B01"},
        )

    def test_vietnamese_asr_variants_and_action_object_threshold(self):
        self.assertEqual(self.ids("Hủy gói xem phim"), {"S11.B02"})
        self.assertEqual(self.ids("Huy goi xem phim"), {"S11.B02"})
        self.assertEqual(self.ids("Mở nhạc"), {"S18.B01"})
        self.assertEqual(self.ids("Mo nhac"), {"S18.B01"})
        self.assertEqual(self.ids("huy"), set())
        self.assertEqual(self.ids("xe đắt"), set())

    def test_multi_intent_and_gated_composite_ownership(self):
        self.assertEqual(
            self.ids("Ghi đã học 30 phút rồi mở playlist"),
            {"S19.B07", "S18.B01"},
        )
        self.assertEqual(
            self.ids("Hủy gói xem phim rồi mở playlist"),
            {"S11.B02", "S18.B01"},
        )
        # Composite S branches remain gated, so their E component branches do not
        # supply partial instructions for the same goal.
        self.assertEqual(self.ids("Dịch rồi gửi vào nhóm"), set())
        self.assertEqual(
            self.ids("Đọc lịch hẹn rồi nhắn giờ qua SMS cho mẹ"),
            set(),
        )
        self.assertEqual(
            self.ids("Nếu trời mưa thì bật đèn"),
            set(),
        )

    def test_history_resolves_objects_without_replaying_old_actions(self):
        history = (
            {"role": "user", "text": "Hủy gói xem phim"},
            {"role": "assistant", "text": "Đã hủy gói."},
        )
        self.assertEqual(self.ids("Mở nhạc đó", history=history), {"S18.B01"})
        self.assertEqual(
            self.ids("Hủy cái đó", history=history),
            {"S11.B02"},
        )
        assistant_only = ({"role": "assistant", "text": "Hủy gói xem phim"},)
        self.assertEqual(self.ids("Mở nó", history=assistant_only), set())

    def test_channel_and_object_cues_prevent_neighbor_branch_matches(self):
        self.assertEqual(self.ids("nhắn cho mẹ"), set())
        self.assertEqual(self.ids("gửi SMS cho mẹ"), {"S06.B02"})
        self.assertEqual(self.ids("gửi vị trí vào nhóm"), {"S06.B05"})
        self.assertEqual(self.ids("gửi lời nhắn vào nhóm"), {"S06.B04"})
        self.assertEqual(self.ids("Đặt xe đạp ở trạm"), {"S12.B03"})
        self.assertEqual(self.ids("Hủy vé máy bay đã đặt"), {"S13.B02"})
        self.assertEqual(self.ids("Hủy vé tàu đã đặt"), {"S13.B05"})
        self.assertEqual(self.ids("Mở playlist và thêm bài vào playlist"),
                         {"S18.B01", "S18.B02"})

    def test_each_enabled_branch_is_reachable_from_a_declared_trigger(self):
        for branch in self.library.branches:
            if branch.evidence != "E":
                continue
            with self.subTest(branch_id=branch.branch_id):
                self.assertTrue(any(
                    branch.branch_id in self.ids(trigger)
                    for trigger in branch.intent_triggers
                ))

    def test_noun_phrases_and_conditional_negation_do_not_create_neighbor_intents(self):
        self.assertEqual(self.ids("thêm bài hát vào danh sách phát"), {"S18.B02"})
        self.assertEqual(self.ids("xóa lịch nhắc uống thuốc"), {"S19.B02"})
        self.assertEqual(self.ids("đăng ký khóa học"), {"S19.B05"})
        self.assertEqual(self.ids("Ghi đã uống thuốc theo lịch"), {"S19.B01"})
        self.assertEqual(self.ids("Nếu không mưa thì mở nhạc"), {"S18.B01"})
        self.assertEqual(self.ids("Nếu không có mưa thì mở nhạc"), {"S18.B01"})
        self.assertEqual(self.ids("Nếu không mưa thì đừng mở nhạc"), set())

    def test_exact_action_eligibility_and_conditional_readers(self):
        selected = retrieve(
            "Hủy gói xem phim subscription_id=SUB-123",
            (),
            {"subscriptions.cancel"},
            self.library,
        )
        self.assertEqual([item.branch_id for item in selected], ["S11.B02"])
        self.assertEqual(selected[0].action_groups, (("subscriptions.cancel",),))
        self.assertEqual(selected[0].conditional_dependencies, ())
        with_reader = retrieve(
            "Hủy gói xem phim subscription_id=SUB-123",
            (),
            {"subscriptions.cancel", "subscriptions.list"},
            self.library,
        )
        self.assertEqual(with_reader[0].conditional_dependencies, ())
        self.assertEqual(self.ids("Hủy gói xem phim", {"subscriptions.list"}), set())

        self.assertEqual(self.ids(
            "Chuyển kênh TV sang VTV1", {"tv.tune"}
        ), set())
        self.assertEqual(self.ids(
            "Chuyển kênh TV sang VTV1", {"tv.tune", "tv.guide"}
        ), {"S18.B07"})

        cart = retrieve(
            "Thêm sản phẩm vào giỏ hàng online product_id=PROD-9 quantity=2",
            (),
            {"ecommerce.add_to_cart"},
            self.library,
        )
        self.assertEqual([item.branch_id for item in cart], ["S16.B01"])
        self.assertEqual(cart[0].conditional_dependencies, ())
        self.assertEqual(cart[0].conditional_actions, ())
        exposed = cart[0].to_dict()
        exposed_tools = {
            tool
            for group in exposed["action_groups"]
            for tool in group
        } | {
            tool
            for group in exposed["conditional_dependencies"]
            for tool in group["tools"]
        } | {
            action["tool"] for action in exposed["conditional_actions"]
        }
        self.assertTrue(exposed_tools <= {"ecommerce.add_to_cart"})

    def test_unavailable_required_reader_needs_exact_fields_or_missing_info_tool(self):
        cancel_only = {"subscriptions.cancel"}
        self.assertEqual(self.ids("Hủy gói xem phim", cancel_only), set())
        for request in (
            "Hủy gói xem phim 12345",
            "Hủy gói xem phim subscription_id=unknown",
            "Hủy gói xem phim subscription_id=n/a",
        ):
            with self.subTest(request=request):
                self.assertEqual(self.ids(request, cancel_only), set())

        clarify = retrieve(
            "Hủy gói xem phim",
            (),
            {"subscriptions.cancel", "sys.ask_missing_info"},
            self.library,
        )
        self.assertEqual([item.branch_id for item in clarify], ["S11.B02"])
        self.assertEqual(clarify[0].conditional_dependencies, ())

        reader_path = retrieve(
            "Hủy gói xem phim",
            (),
            {"subscriptions.cancel", "subscriptions.list"},
            self.library,
        )
        self.assertEqual([item.branch_id for item in reader_path], ["S11.B02"])
        self.assertEqual(
            [dependency.tools for dependency in reader_path[0].conditional_dependencies],
            [("subscriptions.list",)],
        )

        relevant_history = ({
            "role": "user",
            "text": "Gói xem phim subscription_id=SUB-123",
        },)
        from_history = retrieve(
            "Hủy cái đó",
            relevant_history,
            cancel_only,
            self.library,
        )
        self.assertEqual([item.branch_id for item in from_history], ["S11.B02"])
        assistant_only = ({
            "role": "assistant",
            "text": "Gói xem phim subscription_id=SUB-123",
        },)
        self.assertEqual(retrieve("Hủy cái đó", assistant_only, cancel_only, self.library), ())

    def test_optional_and_alternative_readers_do_not_block_exact_paths(self):
        call_search = retrieve(
            "Gọi điện cho mẹ",
            (),
            {"phone.call", "contacts.search"},
            self.library,
        )
        self.assertEqual([item.branch_id for item in call_search], ["S06.B01"])
        self.assertEqual(
            [dependency.tools for dependency in call_search[0].conditional_dependencies],
            [("contacts.search",)],
        )

        call_direct = retrieve(
            "Gọi điện cho mẹ phone_number=+84912345678",
            (),
            {"phone.call"},
            self.library,
        )
        self.assertEqual([item.branch_id for item in call_direct], ["S06.B01"])
        self.assertEqual(call_direct[0].conditional_dependencies, ())

        email_id_path = retrieve(
            "Soạn nháp trả lời email email_id=MAIL-123",
            (),
            {"email.create_draft", "email.read"},
            self.library,
        )
        self.assertEqual(email_id_path, ())  # S07.B03 remains gated evidence S.
        email_branch = next(branch for branch in self.library.branches
                            if branch.branch_id == "S07.B03")
        list_dependency = next(dependency for dependency in email_branch.conditional_dependencies
                               if dependency.tools == ("email.list",))
        self.assertTrue(skills._dependency_input_present(list_dependency, ("email_id=MAIL-123",)))
        self.assertFalse(skills._dependency_input_present(list_dependency, ("email_id=unknown",)))
        self.assertEqual(
            skills._ready_action_groups(
                email_branch,
                {"email.create_draft"},
                ("to=ana@example.com subject=Re body=Thanks",),
            ),
            (("email.create_draft",),),
        )
        self.assertEqual(
            retrieve(
                "Soạn nháp trả lời email",
                (),
                {"email.create_draft", "email.read"},
                self.library,
            ),
            (),
        )

        email_fields = retrieve(
            "Soạn nháp email to=ana@example.com subject=Re body=Thanks",
            (),
            {"email.create_draft"},
            self.library,
        )
        self.assertEqual(email_fields, ())  # Explicit parameters do not override evidence S.

    def test_shared_instructions_are_deduplicated_and_guidance_is_immutable_json(self):
        selected = retrieve(
            "Hủy gói xem phim rồi mở playlist",
            (),
            self.all_tools,
            self.library,
        )
        self.assertEqual({item.branch_id for item in selected}, {"S11.B02", "S18.B01"})
        ids = [
            instruction["id"]
            for item in selected
            for instruction in item.to_dict()["shared_instructions"]
        ]
        self.assertEqual(len(ids), len(set(ids)))
        json.dumps([item.to_dict() for item in selected], ensure_ascii=False)
        with self.assertRaises(AttributeError):
            selected[0].branch_id = "changed"

    def test_retrieval_is_deterministic_and_bounded_on_cpu(self):
        request = "Hủy gói xem phim rồi mở playlist"
        expected = [item.to_dict() for item in retrieve(request, (), self.all_tools, self.library)]
        start = time.perf_counter()
        for _ in range(10):
            self.assertEqual(
                [item.to_dict() for item in retrieve(request, (), self.all_tools, self.library)],
                expected,
            )
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0)

    def test_retrieval_input_is_bounded_and_does_not_echo_private_history(self):
        with self.assertRaises(ValueError):
            retrieve("x" * 8_193, (), self.all_tools, self.library)
        history = (
            {"role": "assistant", "text": "GOLD_PRIVATE_MARKER"},
        )
        output = json.dumps(
            [item.to_dict() for item in retrieve("Mở playlist", history, self.all_tools, self.library)],
            ensure_ascii=False,
        )
        self.assertNotIn("GOLD_PRIVATE_MARKER", output)


if __name__ == "__main__":
    unittest.main()
