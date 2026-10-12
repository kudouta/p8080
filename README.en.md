English | [日本語](README.md)

# p8080

An Intel 8080 assembler and disassembler. One tool takes you from disassembling a ROM and working out what it does, to reassembling it back into the same bytes. Use it as a command or as a Python module.

p8080 is a port of [pz80](https://github.com/kudouta/pz80), a tool for the Z80, to the 8080. Usage and the config file format are the same as pz80. The difference is the instruction syntax: p8080 uses Intel mnemonics (`MOV A,M` / `LXI H,nn` / `JMP`).

## Features

* **Disassembly you can reassemble**: the output of `disasm` assembles with `asm` as-is and matches the original binary.
* **Separating code from data**: `walk` follows the control flow from the entry points and reports the data ranges. With `--auto-entry`, it also finds jump targets in jump tables and similar structures.
* **Keep your analysis in a config file**: names for addresses, comments, and table layouts (such as runs of `dw`) written in a Python config file are reflected in the disassembly. Regenerating the output does not lose them.
* **Multiple ROM chips**: place each ROM file at its own address. For ROMs that encrypt only the instruction bytes, if the scheme can be decrypted from the address and the byte value, you can write the decryption as a function.
* **An assembler you extend from Python**: for what `INCLUDE` or macros would do, build the source in Python and pass it in. Conditional assembly (`IF` / `ELSEIF` / `-D`) is built into the assembler.

## Intel mnemonics

Write instructions in the syntax of Intel's 8080 manual. Z80 syntax (`LD` / `JP (HL)` and so on) is an error.

| To do this | p8080 (Intel) | Z80 syntax |
| --- | --- | --- |
| Load an immediate into A | `MVI A, 0x10` | `LD A, 0x10` |
| Write to the memory HL points to | `MOV M, A` | `LD (HL), A` |
| Load a 16-bit immediate into HL | `LXI H, 0x1234` | `LD HL, 0x1234` |
| Load A from an address | `LDA 0x2000` | `LD A, (0x2000)` |
| Unconditional jump | `JMP loop` | `JP loop` |
| Jump if zero | `JZ loop` | `JP Z, loop` |

**On the 8080, `JP` is a conditional jump: "jump if positive".** It is spelled the same as the Z80's unconditional `JP nn`, so take care not to mix them up. `CP` is the same story: on the 8080 it is "call if positive" (compare is `CMP` / `CPI`).

For the details of the syntax, see [Assembly language](guide/language.md) (in Japanese).

## About this repository

This repository is a **snapshot** of the public part of the author's working repository, with one commit per release. It does not include the development history, the tests, or the development documents. Each release has a tag such as `v0.1.0`.

**No support is provided.** Issues are open, but a reply or a fix is not guaranteed. This is one person's tool, made available in a usable form. Use and modify it freely under the MIT License. If you need something fixed, fork it.

## Installation

Requires Python 3.10 or later.

```bash
pip install git+https://github.com/kudouta/p8080.git
```

To install a specific release, add the tag at the end (for example `p8080.git@v0.1.0`). You can also get the source and install from it.

```bash
cd p8080
pip install .
```

## Getting started

```bash
# Assemble
p8080 asm -f source.asm -o output.bin

# Separate code from data and save the result as a config file
p8080 walk -i rom.bin -e RST7 --auto-entry > rom_config.py

# Disassemble with the config file (-n outputs only the reassemblable form)
p8080 disasm -i rom.bin -c rom_config.py -n -o rom.asm
```

`-e RST7` is the interrupt entry. When the 8080 accepts an interrupt, it executes an instruction that external circuitry places on the data bus (usually `RST n`). Which `RST` is used depends on the board's wiring, so you specify it when you read a ROM.

The whole process of working out a ROM is explained with a practice ROM in **[ROM analysis workflow](guide/workflow.md)** (in Japanese).

From Python:

```python
from p8080 import assemble, disassemble, walk

binary = assemble("    ORG 0x100\n    MVI A, 42\n    RET\n")
lines = disassemble(binary, start_address=0x100)
data_regions = walk(binary, extra_entries=["RST7"])
```

## Documentation

The documents below are written in Japanese. The commands, options, config keys, and code examples in them are the same in any language.

| | Contents |
| --- | --- |
| **[ROM analysis workflow](guide/workflow.md)** | Go through `walk` → `disasm` → naming → reassembly with a practice ROM |
| **[CLI reference](guide/cli.md)** | Options and output of `asm` / `disasm` / `walk` |
| **[Config file](guide/config.md)** | Every key of the config file passed with `-c` (`bins` / `data` / `labels` / `equ` / `comments`, and more) |
| **[Assembly language](guide/language.md)** | The syntax you can write in `.asm`: numbers, directives, conditional assembly, labels, expressions |
| **[Python API](guide/python-api.md)** | Functions, classes, and return values for use as a module |
| **[Change log](CHANGELOG.md)** | What changed for users in each release |

## Language in the source

**Comments and docstrings are in Japanese.** This keeps the source easiest for the author to maintain, and there are no plans to translate them into English. The documents under `guide/` are also in Japanese.

Everything you interact with is in English: CLI help, error messages, the lines `--auto-entry` prints, and the API names (function names, argument names, key names). **This boundary is enforced by a test, so no Japanese string reaches the user.**

## License

This project is released under the [MIT License](LICENSE).
