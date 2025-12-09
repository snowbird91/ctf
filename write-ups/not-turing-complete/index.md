---
layout: post
title: "not-turing-complete"
categories: [misc, vuwctf2025]
date: 2025-12-08 16:00:00 -0500
writeup: true
permalink: /write-ups/not-turing-complete/
order: 11
---

**VuwCTF 2025**

I played VuwCTF 2025 with tjcsc. We got 5th place!

**Challenge:** not-turing-complete  
**Category:** Misc  
**Author:** maxster  
**Flag:** ``VuwCTF{Tur1NG_w4s_r1ght_0Oa0}``

---

## My initial read / first impressions

The description bragged about a "Not Turing-Complete Interpreter" with only three integer variables (`a`, `b`, `c`) and basic arithmetic/bitwise operators. They give us three files in the challenge. I started by opening them to see what the "language" actually was:

```bash
ls turing
# interpreter.py  parser.py  server.py
```

### Peeking at the parser and interpreter

I dumped the important bits (only three variables, one expression per line, no loops):

```bash
sed -n '1,200p' turing/parser.py
```

- Left-hand side is **only** one of `a`, `b`, or `c`.
- Right-hand side can be:
  - a literal integer (`int(token, 0)` so hex like `0xff` works),
  - a variable (`a`, `b`, or `c`),
  - or a single binary operation (`+ - * / ^ & |`) whose operands are themselves literals/variables.
- No parentheses, no chaining of multiple operators in one line. If you want multiple operations, you write multiple lines.
- It eagerly validates, so anything out of spec aborts with an error.

The interpreter just walks the parsed `(lhs, rhs)` list in order and evaluates each `rhs` recursively. Division is integer floor (`//`), and all numbers are Python `int`s (so arbitrary precision). No automatic 32-bit wraparound happens unless we add it ourselves with `& 0xffffffff`.

### The server harness: what is being checked?

The `server.py` is the "judge". I read it fully:

```bash
sed -n '1,200p' turing/server.py
```

Key details:
- It reads user program lines until a line that is literally `EOF`.
- It runs **10 trials**. Each trial:
  1. Generates 32 random bytes: `scramble = secrets.token_bytes(32)`.
  2. Sets `a = int.from_bytes(scramble, 'little')` (so `a` initially holds the entire 256-bit scramble in little-endian).
  3. Runs our program.
  4. Checks whether final `a` equals `xxhash.xxh32(scramble)` interpreted as big-endian (`int.from_bytes(...,'big')`).
- If any trial fails, we don't get the flag.

So the whole game is: **implement xxHash32 of a 32-byte message using only straight-line code with three registers and the given operators.** No loops, no conditionals, but we can have arbitrarily many lines.

---

## Plan of attack

xxHash32 is pretty friendly: it's entirely additions, XORs, multiplies, rotates, and some shifts. The difficulty is:
- We only have three registers.
- We can't write `a = (a << 13) | (a >> 19)` directly with one operator; we must spell it out.
- We need to extract the eight 32-bit words of the 32-byte input from the single 256-bit integer sitting in `a`.

Luckily, the interpreter uses unbounded Python integers, so I can treat the entire 256-bit scramble as a big integer and slice words out by dividing by powers of two. I decided to:
1. Copy the original input from `a` into `b` for safekeeping (since `a` will get overwritten a lot).
2. Keep a running 256-bit "accumulator" in `b` by packing 32-bit chunks into its higher bits. This lets me store partial hash state without losing the original words.
3. Hardcode all loop unrolling: 4 lanes, 2 words each (xxHash32's main loop on 16 bytes) for a total of 8 words.
4. After the main loop, pull the accumulated hash out of the top of `b`, do the length addition (`+ 32`), and perform the final avalanche steps.

All wraparound is done explicitly with `& 0xffffffff`.

---

## Reconstructing xxHash32 as straight-line code

I wrote a small Python helper to generate the actual DSL program for me so I wouldn't make hand-typing mistakes. Constants I used (from the xxHash32 spec):

```python
PRIME1 = 0x9E3779B1
PRIME2 = 0x85EBCA77
PRIME3 = 0xC2B2AE3D
PRIME4 = 0x27D4EB2F  # not directly used in the 32-byte case
PRIME5 = 0x165667B1  # not used because length >= 16
```

The rotation schedule:
- Per-word round: rotate left 13 bits.
- After processing each lane: rotate v1/v2/v3/v4 by 1, 7, 12, 18 bits respectively, then sum them to form the main hash value.
- Final avalanche: XOR >>15, *PRIME2, XOR >>13, *PRIME3, XOR >>16.

### Extracting words from the 256-bit input

Because `a` starts as `int.from_bytes(scramble, 'little')`, the lowest 32 bits are word 0, next 32 bits are word 1, etc. To extract word `i`:

1. `c = b & (2**256 - 1)` (mask to 256 bits, probably redundant but kept it).
2. Repeat `c = c / 2**32` exactly `i` times.
3. `c = c & 0xffffffff` to keep just that 32-bit word.

Shifts are integer divisions in this DSL because division is floor.

### Implementing rotate-left

`rotl(a, r)` becomes:

```
c = a * (1 << r)
c = c & 0xffffffff
a = a & 0xffffffff           # clear any high bits from earlier
a = a / (1 << (32 - r))
a = c | a
a = a & 0xffffffff
```

Rinse and repeat for each needed rotation amount.

### Putting it all together

Here's the exact generator I used (kept in my notes as a one-off Python script).

I put it in `turing/generate_program.py`. Run it with:

```bash
python3 turing/generate_program.py
# This writes the DSL into `turing/program.txt`.
```

The script `turing/generate_program.py`:

```python
# builds the straight-line program into program.txt
MASK32 = 0xffffffff
SHIFT32 = 1 << 32
BASE = 1 << 256          # for packing/unpacking the accumulator in b
INPUT_MASK = BASE - 1
PRIME1 = 2654435761
PRIME2 = 2246822519
PRIME3 = 3266489917
v_inits = [(PRIME1 + PRIME2) % (1<<32), PRIME2 % (1<<32), 0, (-PRIME1) % (1<<32)]
rot_out = [1, 7, 12, 18]
word_indices = [[0,4], [1,5], [2,6], [3,7]]
rot_chunk = 13

class Builder:
    def __init__(self): self.lines = []
    def lit(self, v): return v if isinstance(v, str) else (str(v) if v < 0 else hex(v))
    def binop(self, t, l, op, r): self.lines.append(f"{t} = {self.lit(l)} {op} {self.lit(r)}")
    def mask32(self, t): self.binop(t, t, '&', MASK32)

def load_word(idx):
    b.binop('c', 'b', '&', INPUT_MASK)
    for _ in range(idx): b.binop('c', 'c', '/', SHIFT32)
    b.mask32('c')

def rotl(bits):
    b.binop('c', 'a', '*', 1 << bits); b.mask32('c'); b.mask32('a')
    b.binop('a', 'a', '/', 1 << (32 - bits)); b.binop('a', 'c', '|', 'a'); b.mask32('a')

def apply_round(idx):
    load_word(idx); b.binop('c', 'c', '*', PRIME2); b.mask32('c')
    b.binop('a', 'a', '+', 'c'); b.mask32('a'); rotl(rot_chunk)
    b.binop('a', 'a', '*', PRIME1); b.mask32('a')

def add_rotated():
    b.binop('c', 'b', '/', BASE); b.binop('c', 'c', '+', 'a'); b.mask32('c')
    b.binop('b', 'b', '&', INPUT_MASK); b.binop('a', 'c', '*', BASE); b.binop('b', 'b', '+', 'a')

b = Builder()

# stash input into b (also zero any garbage above 256 bits)
b.binop('b', 'a', '+', 0); b.binop('b', 'b', '&', INPUT_MASK)

for lane in range(4):
    b.binop('a', v_inits[lane], '+', 0); b.mask32('a')
    for wi in word_indices[lane]: apply_round(wi)
    rotl(rot_out[lane]); add_rotated()

# pull hash out of b's top 32 bits, add length=32, avalanche
b.binop('a', 'b', '/', BASE); b.mask32('a'); b.binop('a', 'a', '+', 32); b.mask32('a')
for shift, mul in [(15, PRIME2), (13, PRIME3), (16, 1)]:
    b.binop('c', 'a', '/', 1 << shift); b.binop('a', 'a', '^', 'c'); b.mask32('a')
    if mul != 1: b.binop('a', 'a', '*', mul); b.mask32('a')

open('turing/program.txt','w').write('\n'.join(b.lines)+'\n')
```

The generated program is about 200 lines; it's the straight-line expansion of all the steps above. (Full file lives at `turing/program.txt`.)

---

## Verifying locally (without the `xxhash` dependency)

The provided `server.py` imports `xxhash`, which I didn't have locally. Rather than install it, I dropped a small reference implementation alongside the DSL tester:

```python
# turing/test_program.py (core parts)
import os
from parser import Parser
from interpreter import Interpreter

PRIME1 = 0x9E3779B1; PRIME2 = 0x85EBCA77; PRIME3 = 0xC2B2AE3D
MASK32 = 0xffffffff

def rotl32(x, r): x &= MASK32; return ((x << r) | (x >> (32 - r))) & MASK32

def xxh32(data: bytes) -> int:
    # 32-byte fast path (seed = 0)
    v1 = (PRIME1 + PRIME2) & MASK32
    v2 = PRIME2 & MASK32
    v3 = 0
    v4 = (-PRIME1) & MASK32
    w = [int.from_bytes(data[i:i+4], 'little') for i in range(0, 32, 4)]
    def round(v, x): return (rotl32(v + x * PRIME2, 13) * PRIME1) & MASK32
    v1, v2, v3, v4 = round(v1, w[0]), round(v2, w[1]), round(v3, w[2]), round(v4, w[3])
    v1, v2, v3, v4 = round(v1, w[4]), round(v2, w[5]), round(v3, w[6]), round(v4, w[7])
    acc = (rotl32(v1,1) + rotl32(v2,7) + rotl32(v3,12) + rotl32(v4,18)) & MASK32
    acc = (acc + 32) & MASK32
    acc ^= acc >> 15; acc = (acc * PRIME2) & MASK32
    acc ^= acc >> 13; acc = (acc * PRIME3) & MASK32
    acc ^= acc >> 16; return acc

def run_tests():
    parser = Parser()
    for line in open('program.txt'):
        if line.strip(): parser.parse_line(line)
    parser.validate()
    interp = Interpreter(parser.code)
    for i in range(100):
        scramble = os.urandom(32)
        interp.initialize(a_value=int.from_bytes(scramble,'little'))
        interp.interpret()
        if interp.variables['a'] != xxh32(scramble):
            raise SystemExit("mismatch")
    print("All tests passed")
```

Running it:

```bash
cd turing
python3 test_program.py
# All tests passed
```

Great! This is good news. Now, to test it on the remote server.

---

## Sending it to the real server

Now that `program.txt` works locally, I piped it to the remote service with `nc`, remembering to append the `EOF` line that the judge expects:

```bash
(cat program.txt; echo EOF) | nc not-turing-complete.challenges.2025.vuwctf.com 9987
```

Output:

```
Running 10 trials to validate your code...
Code accepted
Flag: VuwCTF{Tur1NG_w4s_r1ght_0Oa0}
```

There we go! The flag was ``VuwCTF{Tur1NG_w4s_r1ght_0Oa0}``. Beautiful!

---

## Takeaways

- Even a "not Turing-complete" toy can compute non-trivial things if you allow unbounded integers and enough straight-line steps.
- Copying the input into another variable (`b`) early was key. It doubled as scratch space to store the accumulator in unused high bits.
- When there's no looping, **generate** the repetitive code. It avoids typos and mirrors the spec exactly.

Thank you for reading my write-up! This was an extremely fun CTF, and I would like to express my appreciation to the organizers for hosting the CTF!

If there’s anything you think I could improve on in future write-ups, please let me know!

Thank you and have a great day!