# -*- coding: utf-8 -*-
"""凉月 C7101 回归:instant_content 条件类的 by_each_trigger_puller 必须是 Bool。

studio 侧(`tools/character-studio`,本机是 work 目录 junction)用布局表复现三行
真实坏行的关键字段,锁住 studio core 副本的门禁与 composer 默认值;
两份副本的 kind 集合一致性由仓库侧
`tools/fantasy-gauntlet-mod-tools/tests/test_client_legality.py` 对照。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO))
sys.path.insert(0, str(STUDIO / "core"))

import wf_ability_composer as composer  # noqa: E402
import wf_client_legality as legality  # noqa: E402
import wf_describe  # noqa: E402


def _bool_problems(kind: str, row: list[str]) -> list[str]:
    return [p for p in legality.client_legality_problems(kind, row)
            if "by_each_trigger_puller" in p]


def _multiply_problems(kind: str, row: list[str]) -> list[str]:
    return [p for p in legality.client_legality_problems(kind, row)
            if "multiply_trigger" in p]


def _option_problems(kind: str, row: list[str]) -> list[str]:
    return legality.option_cell_problems(kind, row)


def _blank(kind: str) -> list[str]:
    layout = wf_describe.layout(kind)
    blocks = layout["blocks"]
    row = [""] * int(layout["ncols"])
    for name in ("precondition1", "precondition2", "precondition3"):
        row[int(blocks[name])] = "0"
    row[int(blocks["trigger"]) if "trigger" in blocks else
        int(blocks["precondition1"]) - 1] = "0"
    row[int(blocks["instant_trigger"])] = "0"
    row[int(blocks["instant_precontent"])] = "(None)"
    row[int(blocks["instant_delay"])] = "0"
    return row


def _real_row(kind: str, effect_kind: str, bool_value: str,
              multiply_value: str = "0") -> list[str]:
    """凉月三行坏行的关键字段复现(1599921 r2 / 1599922 r2 / 159992 r5)。"""
    layout = wf_describe.layout(kind)
    blocks = layout["blocks"]
    base = int(blocks["instant_content"])
    row = _blank(kind)
    row[base] = effect_kind
    row[base + 1] = "5" if kind == "leader_ability" else "0"
    row[base + 4] = row[base + 5] = "10000"
    row[base + 25] = bool_value
    row[base + 28] = multiply_value
    # 1.4.136 起 Option 列必须写官方哨兵(空串 = Some(null)/Some(0) ->
    # 描述生成器 F1009,2026-10-06 凉月实锤)。
    for offset in (15, 16, 17, 18):
        row[base + offset] = "(None)"
    if effect_kind in ("0", "24"):
        row[base + 14] = "(None)"
    return row


class InstantBoolRegressionTest(unittest.TestCase):
    CASES = (("ability", "0"), ("ability", "24"), ("leader_ability", "489"))

    def test_real_preimage_rows_are_rejected(self) -> None:
        for kind, effect_kind in self.CASES:
            with self.subTest(kind=kind, effect=effect_kind):
                problems = _bool_problems(kind, _real_row(kind, effect_kind, ""))
                self.assertEqual(1, len(problems), problems)
                self.assertIn("C7101", problems[0])

    def test_real_fixed_rows_pass(self) -> None:
        for kind, effect_kind in self.CASES:
            with self.subTest(kind=kind, effect=effect_kind):
                self.assertEqual([], legality.client_legality_problems(
                    kind, _real_row(kind, effect_kind, "false")))

    def test_uppercase_and_false_literals_accepted(self) -> None:
        for kind, effect_kind in self.CASES:
            for literal in ("TRUE", "True", "FALSE", "false"):
                with self.subTest(kind=kind, literal=literal):
                    self.assertEqual([], _bool_problems(
                        kind, _real_row(kind, effect_kind, literal)))

    def test_empty_multiply_trigger_is_rejected(self) -> None:
        for kind, effect_kind in self.CASES:
            with self.subTest(kind=kind, effect=effect_kind):
                problems = _multiply_problems(
                    kind, _real_row(kind, effect_kind, "false", ""))
                self.assertEqual(1, len(problems), problems)
                self.assertIn("C7050", problems[0])
                self.assertEqual([], _multiply_problems(
                    kind, _real_row(kind, effect_kind, "false", "0")))
                self.assertEqual([], _multiply_problems(
                    kind, _real_row(kind, effect_kind, "false", "(None)")))

    def test_composer_writes_the_bool_for_condition_kinds(self) -> None:
        for kind, column in (("ability", 72), ("leader_ability", 70)):
            for effect_kind in ("0", "24", "489"):
                with self.subTest(kind=kind, effect=effect_kind):
                    out = composer.generate(
                        dst_key="1599921", mode="instant", trigger_kind="20",
                        effect_kind=effect_kind, target="0", value=10,
                        value_max=10,
                        blank_factory=lambda key: {
                            "key": "fixture", "kind": kind, "line": None,
                            "ncols": int(wf_describe.layout(kind)["ncols"]),
                            "row": _blank(kind), "desc": ""},
                        metadata=composer.composer_meta,
                        element_index=lambda key: 0)
                    self.assertEqual("false", out["row"][column])
                    self.assertEqual("0", out["row"][column + 3])
                    self.assertEqual([], _bool_problems(kind, out["row"]))
                    self.assertEqual([], _multiply_problems(kind, out["row"]))

    def test_kind_set_invariants(self) -> None:
        kinds = legality.INSTANT_CONTENT_BOOL_KINDS
        self.assertEqual(120, len(kinds))
        for value in ("0", "1", "24", "489", "718"):
            self.assertIn(value, kinds)
        for value in ("32", "55", "211", "629"):
            self.assertNotIn(value, kinds)
            self.assertNotIn(value, legality.INSTANT_CONTENT_MULTIPLY_KINDS)
        self.assertEqual(41, len(legality.INSTANT_CONTENT_MULTIPLY_KINDS))

    def test_option_kind_sets_and_rules(self) -> None:
        limits = legality.INSTANT_CONTENT_LIMIT_KINDS
        self.assertEqual(78, len(limits))
        for value in ("0", "24", "26", "489", "718"):
            self.assertIn(value, limits)
        for value in ("32", "211", "226", "629"):
            self.assertNotIn(value, limits)
        accumulation = legality.INSTANT_CONTENT_MAX_ACCUMULATION_KINDS
        self.assertEqual(95, len(accumulation))
        self.assertIn("0", accumulation)
        self.assertIn("24", accumulation)
        self.assertNotIn("489", accumulation)
        # 真实坏行形态:Option 列空串必被拒。
        for kind, effect_kind in self.CASES:
            with self.subTest(kind=kind, effect=effect_kind):
                broken = _real_row(kind, effect_kind, "false")
                base = int(wf_describe.layout(kind)["blocks"]["instant_content"])
                for offset in (15, 16, 17, 18):
                    broken[base + offset] = ""
                problems = _option_problems(kind, broken)
                self.assertEqual(4, len(problems), problems)
                self.assertTrue(all("F1009" in p or "undefined" in p
                                    for p in problems))
        # 非法 accepted_levels 值同样必须被拒(limit 为 Some 时崩)。
        for kind in ("ability", "leader_ability"):
            base = int(wf_describe.layout(kind)["blocks"]["instant_content"])
            row = _real_row(kind, "0", "false")
            row[base + 18] = "4"
            problems = _option_problems(kind, row)
            self.assertEqual(1, len(problems), problems)
            self.assertIn("resolveEndPowerFlipLevels", problems[0])
            for value in ("(None)", "1", "2", "3", "11", "12"):
                row[base + 18] = value
                with self.subTest(kind=kind, value=value):
                    self.assertEqual([], _option_problems(kind, row))

    def test_composer_writes_none_option_defaults(self) -> None:
        for kind in ("ability", "leader_ability"):
            base = int(wf_describe.layout(kind)["blocks"]["instant_content"])
            for effect_kind in ("0", "24", "489"):
                with self.subTest(kind=kind, effect=effect_kind):
                    out = composer.generate(
                        dst_key="1599921", mode="instant", trigger_kind="20",
                        effect_kind=effect_kind, target="0", value=10,
                        value_max=10,
                        blank_factory=lambda key: {
                            "key": "fixture", "kind": kind, "line": None,
                            "ncols": int(wf_describe.layout(kind)["ncols"]),
                            "row": _blank(kind), "desc": ""},
                        metadata=composer.composer_meta,
                        element_index=lambda key: 0)
                    row = out["row"]
                    for offset in (15, 16, 17, 18):
                        self.assertEqual("(None)", row[base + offset])
                    if effect_kind in ("0", "24"):
                        self.assertEqual("(None)", row[base + 14])
                    self.assertEqual([], _option_problems(kind, row))


if __name__ == "__main__":
    unittest.main()
