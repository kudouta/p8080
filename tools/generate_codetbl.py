#!/usr/bin/env python3
"""
i8080_opcodes.yaml から i8080.py の _codetbl セクションを自動生成するスクリプト。

使用方法:
    python tools/generate_codetbl.py

i8080_opcodes.yaml を参照データとして読み込み、src/p8080/i8080.py 内の
BEGIN GENERATED / END GENERATED マーカー間のコードを置き換えます。

pz80 の tools/generate_codetbl.py を移植したもの。pz80 との違いは次のとおり。

* 出力するフィールドが 8080 のもの（`rel` `ext` `undoc` は無く、`access` `flow` がある）。
* 列挙型のフィールド（`type` `access` `flow`）の**値**も検査する。`flow: jmup` の
  ような綴り違いは、walk が「制御を変えない命令」として黙って読み進める原因になり、
  テストでは見つけにくいため。
* パスをスクリプトの位置から決める（どのディレクトリから実行してもよい）。
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install it with: pip install pyyaml")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "src" / "p8080" / "i8080_opcodes.yaml"
CPU_PATH = ROOT / "src" / "p8080" / "i8080.py"
BEGIN_MARKER = "    # <<< BEGIN GENERATED FROM i8080_opcodes.yaml >>>"
END_MARKER = "    # <<< END GENERATED >>>"
INDENT = "        "  # 8スペース（クラス本体のインデント）

# i8080.py の _codetbl へ出力する既知フィールド
KNOWN_FIELDS = {"code", "bytes", "asm", "type", "jmp", "access", "flow"}

# 意図的に i8080.py へ渡さないフィールド。現在は無い。
# pz80 ではテスト専用メタデータ `alt_encoding` をここで落としていたが、p8080 は
# 未定義命令（冗長エンコード）を収録しないので該当するフィールドが無い。
# テスト専用のフィールドを足すときは、理由を添えてここへ登録すること。
DROPPED_FIELDS = set()

# 列挙型フィールドに許す値。意味は docs/opcode-table-fields.md を参照。
ALLOWED_VALUES = {
    "type": {"word"},
    "access": {"r", "w", "imm"},
    "flow": {
        "jump",
        "jump-cc",
        "call",
        "call-cc",
        "return",
        "return-cc",
        "jump-indirect",
        "rst",
    },
}

# 生成コードに入れる区切りコメント。8080 はプレフィックスを持たないので、
# 上位 2 ビットで 4 つに分ける（User's Manual の命令コード表の並びと同じ見方）。
# キーは各区画の先頭のオペコード。
SECTION_COMMENTS = {
    0x00: "        # 00xxxxxx: データ転送・16ビット演算・INR/DCR/MVI・ローテート\n",
    0x40: "        # 01xxxxxx: MOV / HLT\n",
    0x80: "        # 10xxxxxx: レジスタ・メモリと A の演算\n",
    0xC0: "        # 11xxxxxx: 分岐・スタック・即値演算・入出力\n",
}


def describe_code(entry):
    """エラーメッセージ用に、エントリのオペコードを文字列にする。

    Args:
        entry (dict): i8080_opcodes.yaml の1エントリ。
            例: {"code": [0xC3], "bytes": 3, "asm": ["jmp", "0x{1}{0}"], ...}

    Returns:
        str: 例: "0xC3"。code が無い場合は "(no code)"。
    """
    return " ".join(f"0x{b:02X}" for b in entry.get("code") or []) or "(no code)"


def check_fields(entry):
    """未知のフィールドが無いことを確かめる。

    YAML へフィールドを追加したまま本スクリプトを追随させ忘れると i8080.py へ
    伝播せず（silently drop）、テストでも検出できないため、ここで検査する。

    Args:
        entry (dict): i8080_opcodes.yaml の1エントリ。
            例: {"code": [0x32], "bytes": 3, "asm": ["sta", "0x{1}{0}"],
                 "type": "word", "access": "w"}

    Raises:
        ValueError: KNOWN_FIELDS にも DROPPED_FIELDS にも属さないフィールドがある場合。
    """
    unknown = set(entry) - KNOWN_FIELDS - DROPPED_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown field(s) {sorted(unknown)} on the entry with "
            f"code=[{describe_code(entry)}]. "
            f"Add them to KNOWN_FIELDS to emit them, or to DROPPED_FIELDS "
            f"(with a reason) if they must not reach i8080.py."
        )


def check_values(entry):
    """列挙型フィールドの値が許された値であることを確かめる。

    Args:
        entry (dict): i8080_opcodes.yaml の1エントリ。
            例: {"code": [0xC2], "bytes": 3, "asm": ["jnz", "0x{1}{0}"],
                 "jmp": 1, "flow": "jump-cc"}

    Raises:
        ValueError: ALLOWED_VALUES に無い値がある場合。
            例: flow: "jmup"
    """
    for field, allowed in ALLOWED_VALUES.items():
        if field not in entry:
            continue
        value = entry[field]
        if value not in allowed:
            raise ValueError(
                f"Invalid value {field}: {value!r} on the entry with "
                f"code=[{describe_code(entry)}]. "
                f"Allowed values: {sorted(allowed)}."
            )


def format_entry(entry):
    """YAMLエントリを Python の dict リテラル文字列に変換する。

    Args:
        entry (dict): i8080_opcodes.yaml の1エントリ。
            例: {"code": [0x32], "bytes": 3, "asm": ["sta", "0x{1}{0}"],
                 "type": "word", "access": "w"}

    Returns:
        str: _codetbl に埋め込む dict リテラル1行分の文字列。
            例: '        {"code": [0x32], "bytes": 3, "asm": ["sta", "0x{1}{0}"],
                 "type": "word", "access": "w"},'

    Raises:
        ValueError: 未知のフィールド、または許されない値がある場合。
    """
    check_fields(entry)
    check_values(entry)

    parts = []

    # code: バイト値リストを 0xNN リテラル表記で出力
    code_items = ", ".join(f"0x{b:02X}" for b in entry["code"]) if entry["code"] else ""
    parts.append(f'"code": [{code_items}]')

    parts.append(f'"bytes": {entry["bytes"]}')

    # asm: 文字列リストをそのまま出力
    asm_items = ", ".join(f'"{t}"' for t in entry["asm"])
    parts.append(f'"asm": [{asm_items}]')

    if "type" in entry:
        parts.append(f'"type": "{entry["type"]}"')
    if "jmp" in entry:
        parts.append(f'"jmp": {entry["jmp"]}')
    if "access" in entry:
        parts.append(f'"access": "{entry["access"]}"')
    if "flow" in entry:
        parts.append(f'"flow": "{entry["flow"]}"')

    return INDENT + "{" + ", ".join(parts) + "},"


def generate_codetbl(entries):
    """エントリリストから _codetbl の Python コード行リストを生成する。

    Args:
        entries (list): i8080_opcodes.yaml を読み込んだエントリのリスト。
            例: [{"code": [0x00], "bytes": 1, "asm": ["nop"]}, ...]

    Returns:
        list: 改行付きのコード行のリスト。
            例: ["    _codetbl = [\\n", "        # 00xxxxxx: ...\\n",
                 '        {"code": [0x00], "bytes": 1, "asm": ["nop"]},\\n', ..., "    ]\\n"]
    """
    lines = []
    lines.append("    _codetbl = [\n")

    for entry in entries:
        code = entry["code"][0] if entry["code"] else None
        if code in SECTION_COMMENTS:
            lines.append(SECTION_COMMENTS[code])

        lines.append(format_entry(entry) + "\n")

    lines.append("    ]\n")
    return lines


def main():
    """`i8080_opcodes.yaml` から命令表を作り、`i8080.py` の生成区間を書き換えます。

    YAML か `i8080.py` が無い、または `i8080.py` に生成区間の目印が無いときは、
    `Error:` を出して終了コード 1 で終わります。
    """
    if not YAML_PATH.exists():
        print(f"Error: {YAML_PATH} not found.")
        sys.exit(1)
    if not CPU_PATH.exists():
        print(f"Error: {CPU_PATH} not found.")
        sys.exit(1)

    with open(YAML_PATH, encoding="utf-8") as f:
        entries = yaml.safe_load(f)

    print(f"Loaded {len(entries)} entries from YAML")

    # i8080.py を読み込み、マーカー間を置き換える
    with open(CPU_PATH, encoding="utf-8") as f:
        cpu_lines = f.readlines()

    begin_idx = end_idx = None
    for i, line in enumerate(cpu_lines):
        if line.rstrip() == BEGIN_MARKER:
            begin_idx = i
        elif line.rstrip() == END_MARKER:
            end_idx = i
            break

    if begin_idx is None or end_idx is None:
        print("Error: generated-section markers not found in i8080.py.")
        print(f"  BEGIN: {BEGIN_MARKER}")
        print(f"  END:   {END_MARKER}")
        sys.exit(1)

    generated = generate_codetbl(entries)

    new_lines = cpu_lines[: begin_idx + 1] + generated + cpu_lines[end_idx:]

    with open(CPU_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Done: {CPU_PATH} updated.")


if __name__ == "__main__":
    main()
