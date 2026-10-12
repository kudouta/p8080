#!/usr/bin/env python3

"""ニーモニック列からオペコードへの符号化。

`asm.py` の 4 責務のうち「符号化」を担う。トークン化済みの命令行を受け取り、
オペコード列と fixups（Pass 2 で埋めるラベル参照の位置情報）を返す。

外部から必要とするのは `I8080` インスタンスと、Pass 1 で確定する定義済みラベル集合
（`defined_labels`）だけ。ラベルのアドレス表そのものは持たず、`Asm` 側が保持する。

`Encoder` をクラスにしているのは、`cpu` を 10 個の関数へ引数で通し続けるより
1 箇所に保持する方が読みやすいため。可変な状態は `defined_labels` のみで、
これは Pass 1 が設定する。

pz80 の `_encoder.py` を移植したもの。8080 に無い次の処理を除いた。

* 相対ジャンプ（`rel`）の fixup。8080 の分岐はすべて 16 ビットの絶対アドレス。
* 数値オペランドが 2 つある命令（`ld (ix+d),n`）。8080 の命令は数値を高々 1 つしか持たない。
* DDCB/FDCB（`ext`）と `bit/res/set` の特別扱い、`ix/iy` の後の `+/-` の判定。

また、`(` を常に式の始まりとして扱う（pz80 は通常の命令では読み飛ばしていた）。
Z80 の `(` はメモリ参照を表すが、8080 の命令にはメモリ参照の括弧が無いため、
`mvi a,(3+4)*2` のように括弧を式の中で使える。
"""

from p8080 import _evaluator
from p8080._util import current_address as _current_address
from p8080._util import format_location as _format_location


class Encoder:
    """トークン列をオペコードへ符号化する。

    Args:
        cpu (i8080.I8080): 命令表・予約語を提供する CPU 定義。
    """

    def __init__(self, cpu):
        """Encoder を初期化します。"""
        self.cpu = cpu

        # Pass 1 が設定する定義済みラベル集合（$ やラベル参照の検証に使う）
        self.defined_labels = None

        # 既知のニーモニック・疑似命令セット (エラー診断用)
        self.known_mnemonics = {key[0] for key in self.cpu.asm_map}
        self.known_mnemonics |= {
            "org",
            "equ",
            "db",
            "defb",
            "dw",
            "defw",
            "ds",
            "defs",
            "end",
        }

    def asm2op(self, asmlist):
        """アセンブルリストからオペコードを生成
          1.数値はpythonでintで認識できるフォーマットであること
          2.数値は適応するオペコードで使用する桁(バイト/ワード)へ自動変換
          3.ラベルは事前検索で抽出済の文字が対象
          4.ラベルは自動変換で仮値(=0)をセットする

        Args:
            asmlist (dict): 1命令分のアセンブル情報。
                            例: {"line": 3, "asm": ["mvi", "a", ",", "0x10"], "base": 0x100, "offset": 0}

        Returns:
            tuple: (opcode, fixups) の2要素タプル。
                opcode (list): 生成されたオペコードバイト列 (例: [0x3E, 0x10])
                fixups (list): Pass 2でアドレス解決が必要な情報のリスト。
                               各要素:
                                 "offset"(int) : opcode 内のバイト位置
                                 "size"(int)   : バイト数 (1 or 2)
                                 "type"(str)   : "byte", "word"
                                 "src"(dict)   : _parse_operands() が返すオペランド辞書

        Raises:
            ValueError: 知らないニーモニック、またはオペランドの数・形が命令に合わない場合。
                オペランドの式の誤りも、解析の途中からそのまま届く。
        """
        if asmlist.get("asm") is None:
            return [], []

        asm = asmlist["asm"]
        mnemonic = asm[0].lower()

        # 未知のニーモニックを早期検出 (_parse_operands が式評価を試みる前)
        if mnemonic not in self.known_mnemonics:
            raise ValueError(
                f"Unknown mnemonic '{asm[0]}' on {_format_location(asmlist['line'], asmlist.get('file'))}: {' '.join(asm)}"
            )

        # オペランドがオペコードに埋め込まれた literal の命令 (RST 0〜7)
        # は、トークン列そのままで asm_map に直接一致する。これを最初に試みる。
        direct = self.cpu.asm_map.get(tuple(t.lower() for t in asm))
        if direct is not None:
            return list(direct["code"]), []

        rs = self.parse_operands(asmlist)
        template_asm = list(asm)

        # オペコード確定
        # 8080 の命令が持つ数値オペランドは高々 1 つ（mvi / lxi / jmp など）。
        match len(rs):
            case 0:
                # 数値無し
                op, fixups = self._encode_no_operand(template_asm)

            case 1:
                # 1オペランド (バイト or ワード)
                op, fixups = self._encode_byte_operand(template_asm, rs[0])
                if len(op) == 0:
                    op, fixups = self._encode_word_operand(template_asm, rs[0])

            case _:
                raise ValueError(
                    f"Invalid operand count or format on {_format_location(asmlist['line'], asmlist.get('file'))}: {asmlist['asm']}"
                )

        return op, fixups

    def parse_operands(self, asmlist):
        """トークンリストからオペランドを抽出・解析する

        Args:
            asmlist (dict): 1命令分のアセンブル情報。
                            例: {"line": 3, "asm": ["mvi", "a", ",", "0x10"], "base": 0x100, "offset": 0}

        Returns:
            list: オペランド情報辞書のリスト。
                  各要素:
                    "value"(int)    : 評価済み数値 (Pass 1では未定義ラベルは仮値 0)
                    "location"(int) : asm リスト内のトークン開始インデックス
                    "length":(int)  : 消費したトークン数
                    例: [{"value": 16, "location": 3, "length": 1}]  # "0x10" の場合
                    例: [{"value": 14, "location": 3, "length": 7}]  # "(3+4)*2" の場合
        """
        asm = asmlist["asm"]
        rs = []
        i = 0

        # pz80 は通常の命令で `(` を読み飛ばしていた（Z80 では `(hl)` のような
        # メモリ参照を表すため）。8080 の命令にはメモリ参照の括弧が無いので、
        # `(` は常に式の始まりになる（判定は `_is_expression_start`）。
        while i < len(asm):
            if not self._is_expression_start(asm, i):
                i += 1
                continue

            val, consumed = self._try_evaluate(asm, i, asmlist)
            if consumed == 0:
                i += 1
                continue

            rs.append(
                {
                    "value": val,
                    "location": i,
                    "length": consumed,
                    "line": asmlist["line"],
                    "file": asmlist.get("file"),
                }
            )
            i += consumed

        return rs

    def _try_evaluate(self, asm, index, asmlist):
        """Pass 1 の式評価を試みます。解析できなければ (None, 0) を返します。

        未定義シンボルだけは再送出します。Pass 1 での定義漏れは後段で拾えず、
        黙って無視すると誤ったオペコードになるためです。

        Args:
            asm (list): トークンリスト。
            index (int): 評価を開始するインデックス。
            asmlist (dict): 対象のアセンブル行（位置情報とベースアドレスに使う）。

        Returns:
            tuple[int | None, int]: (評価結果, 消費したトークン数)。
        """
        try:
            return self.evaluate_expression(
                asm,
                index,
                None,  # pass1 用評価 (address_map=None)
                asmlist["line"],
                current_address=_current_address(asmlist),
                file_name=asmlist.get("file"),
            )
        except ValueError as e:
            if "Undefined symbol" in str(e):
                raise
            # 式の解析に失敗しても、ここでは無視して進む
            return None, 0

    def _is_expression_start(self, tokens, index):
        """指定されたインデックスのトークンが式の開始点となりうるかを判定します。

        Args:
            tokens (list): トークンリスト (例: ["mvi", "a", ",", "0x10"])
            index (int): 判定対象トークンのインデックス。

        Returns:
            bool: 式の開始点となりうる場合はTrue。
                例: ["mvi", "a", ",", "(", "3", "+", "4", ")"] の index 3 ("(") は True。

        Note:
            pz80 では '(' を式の開始とみなさなかった（Z80 の `(hl)` などメモリ参照の
            括弧と区別するため）。8080 にはメモリ参照の括弧が無いので、'(' は
            式の開始になる。
        """
        token = tokens[index]

        return not (
            # 予約語は式の開始点とはみなさない
            token.lower() in self.cpu.reserved
            # カンマや閉じ括弧類は式の開始点とはみなさない
            or token in [",", ")", "]", "}"]
        )

    def _find_expression_end(self, tokens, start_index):
        """式の開始インデックスから、式が終わるインデックスを見つけます。

        Args:
            tokens (list): トークンリスト (例: ["lxi", "h", ",", "LABEL", "+", "1"])
            start_index (int): 式の開始インデックス。

        Returns:
            int: 式が終わるインデックス（終端トークンの次の位置）。
                カンマまたは対応しない閉じ括弧の手前で停止する。
        """
        end_index = start_index
        paren_balance = 0
        while end_index < len(tokens):
            token = tokens[end_index]
            if token == "(":
                paren_balance += 1
            elif token == ")":
                paren_balance -= 1
            elif token == "," and paren_balance == 0:
                break
            if paren_balance < 0:
                break
            end_index += 1
        return end_index

    def evaluate_expression(
        self,
        tokens,
        start_index,
        address_map,
        line_num,
        current_address=None,
        file_name=None,
    ):
        """ExpressionEvaluatorを使用して、トークンリストから式を評価します。

        Args:
            tokens (list): トークンリスト (例: ["LABEL", "+", "1"])
            start_index (int): 評価を開始するインデックス。
            address_map (dict or None): ラベルとアドレスの対応辞書 (例: {"LABEL": 0x100})。Noneの場合はPass 1として扱い、ラベルには仮値 0 を返す。
            line_num (int): エラー報告用の行番号。
            current_address (int or None): $ として解決する現在のアドレス。
            file_name (str or None): エラー報告用のソース識別子。

        Returns:
            tuple: (value, consumed) の2要素タプル。
                value (int or None): 式の評価結果。トークンがない場合はNone。
                consumed (int): 消費したトークン数。
        """
        end_index = self._find_expression_end(tokens, start_index)

        expr_tokens = tokens[start_index:end_index]
        consumed = len(expr_tokens)

        if not expr_tokens:
            return None, 0

        # Pass 1では、address_mapはNoneです。検証のために定義済みラベルのセットを渡します。
        defined_labels_pass1 = self.defined_labels if address_map is None else None
        evaluator_instance = _evaluator.ExpressionEvaluator(
            expr_tokens,
            self.cpu.reserved,
            line_num,
            address_map,
            defined_labels_pass1,
            current_address=current_address,
            file_name=file_name,
        )
        value = evaluator_instance.evaluate()

        return value, consumed

    def _encode_no_operand(self, s):
        """オペランドなし命令の処理

        Args:
            s (list): トークンリスト (例: ["nop"])

        Returns:
            tuple: (opcode, fixups) の2要素タプル。
                opcode (list): オペコードバイト列 (例: [0x00])
                fixups (list): 常に空リスト []
        """
        ref = s[:]
        u = self._lookup_opcode(ref)
        return (u[0]["code"], []) if u else ([], [])

    def _encode_byte_operand(self, s, d):
        """オペコード1バイト

        Args:
            s (list): トークンリスト (例: ["mvi", "a", ",", "0x10"])
            d (dict): _parse_operands() が返すオペランド情報辞書。
                {"value": int, "location": int, "length": int}
                例: {"value": 16, "location": 3, "length": 1}

        Returns:
            tuple: (opcode, fixups) の2要素タプル。
                opcode (list): オペコードバイト列 (例: [0x3E, 0x10])
                fixups (list): アドレス解決情報のリスト。
                               各要素:
                                 "offset"(int):
                                 "size"(int): 1
                                 "type"(str): "byte"
                                 "src"(dict):
        """
        # トークンリストからオペコードを検索
        # self._codetbl[]["asm"] と バイト(0x{0})の検索

        r = []
        fixups = []
        val = d["value"]
        ref = s[:]
        length = d.get("length", 1)
        # 数値または式の箇所をプレースホルダーに置換
        ref[d["location"] : d["location"] + length] = ["0x{0}"]
        p = self._lookup_opcode(ref)
        if not p:
            return r, fixups

        u = p[0]
        r = list(u["code"])

        # 符号付き8bit (-128) ～ 符号なし8bit (255) の範囲を許容
        self.check_range(val, -128, 255, "Byte", d)

        val_byte = val & 0xFF

        r.append(val_byte)
        fixups.append({"offset": len(r) - 1, "size": 1, "type": "byte", "src": d})
        return r, fixups

    def _encode_word_operand(self, s, d):
        """オペコード2バイト

        Args:
            s (list): トークンリスト (例: ["lxi", "h", ",", "0x1234"])
            d (dict): _parse_operands() が返すオペランド情報辞書。
                {"value": int, "location": int, "length": int}
                例: {"value": 0x1234, "location": 3, "length": 1}

        Returns:
            tuple: (opcode, fixups) の2要素タプル。
                opcode (list): オペコードバイト列 (例: [0x21, 0x34, 0x12])
                fixups (list): アドレス解決情報のリスト。
                               各要素:
                                 "offset"(int) :
                                 "size"(int) : 2
                                 "type"(str) : "word"
                                 "src"(dict) :
        """
        # トークンリストからオペコードを検索
        # self._codetbl[]["asm"] と ワード(0x{1}{0})の検索

        r = []
        fixups = []
        val = d["value"]
        # 符号付き16bit (-32768) ～ 符号なし16bit (65535) の範囲を許容
        self.check_range(val, -32768, 65535, "Word", d)

        ref = s[:]
        length = d.get("length", 1)
        # 数値または式の箇所をプレースホルダーに置換
        ref[d["location"] : d["location"] + length] = ["0x{1}{0}"]
        u = self._lookup_opcode(ref)

        if not u:
            return r, fixups

        r = list(u[0]["code"])
        # 符号付き対応のためマスク処理
        val_word = val & 0xFFFF
        r.append(val_word & 0xFF)
        r.append((val_word >> 8) & 0xFF)

        fixups.append({"offset": len(r) - 2, "size": 2, "type": "word", "src": d})
        return r, fixups

    @staticmethod
    def check_range(value, low, high, kind, d):
        """オペランド値の範囲を検査します。

        Args:
            value (int): 検査する値。
            low (int): 下限（含む）。
            high (int): 上限（含む）。
            kind (str): エラーメッセージ中の種別名（"Byte" / "Word"）。
            d (dict): オペランド情報。位置情報（line / file）に使う。

        Raises:
            ValueError: 範囲外の場合。

        Note:
            `asm.py` の Pass 2 も同じ検査をするため、そちらからも呼ばれます
            （メッセージ形式を 1 箇所に保つため）。
        """
        if not (low <= value <= high):
            raise ValueError(
                f"{kind} value {value} out of range on "
                f"{_format_location(d['line'], d.get('file'))} "
                f"(expected {low} to {high})"
            )

    def _lookup_opcode(self, s):
        """オペコード検索

           小文字変換してCPUコードのリストから検索

        Args:
            s (list): プレースホルダー置換済みトークンリスト
                      例: ["mvi", "a", ",", "0x{0}"]

        Returns:
            list: 一致した命令情報辞書を1要素持つリスト。不一致の場合は空リスト。
                  例: [{"code": [0x3E], "bytes": 2, "asm": ["mvi", "a", ",", "0x{0}"]}]
        """
        key = tuple(y.lower() for y in s)
        item = self.cpu.asm_map.get(key)
        return [item] if item else []
