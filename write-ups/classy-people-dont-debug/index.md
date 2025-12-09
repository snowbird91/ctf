---
layout: post
title: "Classy_People_Dont_Debug"
categories: [rev, vuwctf2025]
date: 2025-12-08 18:30:00 -0500
writeup: true
permalink: /write-ups/classy-people-dont-debug/
order: 12
---

**VuwCTF 2025**

I played VuwCTF 2025 with tjcsc. We got 5th place!

**Challenge:** Classy_People_Dont_Debug  
**Category:** Reverse Engineering  
**Author:** Aterlone
**Flag:** ``VuwCTF{very_classy_d0'nt_6ou_s33}``

---

## My initial read / first impressions

- The statement was already teasing: “Classy people never debug… static analysis is the intended way.” I'm sensing anti-debug traps...
- Only one file was given, an ELF:

```
cd classy-folder
chmod +x Classy
file Classy
# ELF 64-bit LSB pie executable, x86-64, dynamically linked, stripped
```

- I usually try a blind run to see usage, but given the warning about dynamic analysis I didn't want to use `strace` or `ltrace`. Instead I took a look at the printable bits:

```
strings -n 5 Classy | head -n 40
# ... SHA256_Init/SHA256_Update/SHA256_Final
# ... ptrace, prctl, strstr, strcasestr, opendir, readdir
# "Static analysis above all!"
# "Enter flag:"
# "Wrong!"
# "Correct!"
# "Modulo by zero"
```

Seeing ptrace/prctl plus those anti-debug strings confirmed the theme: it will probably scan `/proc`, look for debuggers/VMs/Frida, and die if anything is attached. Welp, time to stay in the realm of static tools.

---

## Recon: quick disassembly sweep

I generated a full disassembly so I could hop around with `sed`/`rg` instead of a live debugger:

```
objdump -Mintel -d Classy > disasm.txt
wc -l disasm.txt
# 2256 disasm.txt lines
```

`.rodata` already looked juicy:

```
objdump -s -j .rodata Classy | sed -n '0x4000,0x4450p'
```

Relevant bits:
- Strings for `/proc/self/maps`, `frida`, `gdb`, `pwndbg`, `/sys/class/dmi/id/product_name`, `VMware`, `VirtualBox`, `QEMU`, `wireshark`… clear anti-VM/anti-debug probes.
- Literal messages: `Static analysis above all!`, `Enter flag:`, `Wrong!`, `Correct!`.
- A large table of bytes starting at offset `0x4180` (more on that later).

---

## Walking the code: where is “main” hiding?

The binary is PIE and stripped, so there’s no symbol named `main`. Entry goes through the C++ runtime as usual, but the real logic sits around `0x33f7`, which is where `_start` eventually lands. I took a closer look in that region:

```
rg -n "33f7" disasm.txt
sed -n '1230,1505p' disasm.txt
```

Key observations from this block:

1. **Anti-debug prelude** (`0x340f–0x34d9`):
   - `prctl(PR_SET_DUMPABLE, 0)` turns off core dumps.
   - `ptrace(PTRACE_TRACEME)` immediately; if it returns `-1`, it bails.
   - Calls into two helper routines (`0x243b`, `0x2584`) that scan `/proc/self/maps` for RWX pages and check for “frida”, “gdb”, “pwndbg”, “radare”, “strace”, and various VM product strings via `/sys/class/dmi/id/product_name` and `/proc/*/comm`.
   - If any of those hit, it prints “Static analysis above all!” and exits.

   What did I get from this?: dynamic tools will trigger the exits, so I have to stay static.

2. **User prompt and input** (`0x34f0–0x3573`):
   - Prints “Enter flag: ” using `std::cout`.
   - Reads a line into a C++ string (`std::getline`).
   - Requires the total length to be exactly `0x21` (33) characters. If not, prints “Wrong!” and returns.

3. **Main flag loop** (`0x35c8–0x36e9`):
   - Iterates an index `i` from 0 to 0x20 (32).
   - For each `i`, it pulls a byte from the big table in `.rodata`:

     ```
     byte table_val = *(0x4180 + 6*i);
     ```

     (the spacing of 6 bytes per entry is odd, but only the first byte of each 6-byte slot matters).

   - Calls a helper at `0x2f88` with signature roughly:

     ```
     uint8_t f(int idx, int dummy_zero, uint8_t table_val);
     ```

   - Compares the returned byte to `flag[i]`. If any mismatch, print “Wrong!” and exit. If all match, print “Correct!”.

So the heart of the problem is to understand `0x2f88` (plus its nested arithmetic helpers) and the 33-byte table to recover the flag characters.

---

## Detouring into the helper jungle (static only)

### The “expensive” trampoline: `0x2bbd`

Almost every helper call starts with `call 0x2bbd`. Disassembling that chunk (`sed -n '730,870p disasm.txt'`) shows:
- It measures time with `clock_gettime` twice and computes a duration.
- It loops a thousand times summing loop counters (probably to waste time).
- If the elapsed nanoseconds exceed `0x5f5e100` (100ms), it returns 1; else 0.

Then the *caller* treats a non-zero result as “bail out early”. This is another anti-debug/anti-trace trick: breakpoints/slow emulation would push runtime over the threshold and make the helper short-circuit. Since we are doing purely static emulation, we can conceptually force this to always return 0.

### Arithmetic helpers

`0x2f88` itself is a small wrapper:

```
int idx = edi;
int dummy = esi;   // always 0 in this binary
uint8_t t = dl;    // table byte

if (slow_guard()) return 0;     // 0x2bbd

// Then a sequence of helper calls:
store(idx *something*)
store(table_byte)
...
fetch char from input string at offset idx
do arithmetic chain
return char
```

The called helpers are tiny:
- `0x38c0`, `0x3936`, `0x3bec`, `0x39c0` etc. are one- or two-liners doing addition, subtraction, multiplication, xor, modulo with small constants.
- There is a “Modulo by zero” string nearby but the modulo helper guards against 0, so it’s safe.

Net result: `0x2f88` is a deterministic function of `(idx, table_val)`, with no external state besides the guard.

Because the logic is spread across many C++ inlined destructors (thanks, stripped binary), re-deriving by hand would be painful. Instead, I decided to **emulate just this function** and ignore the anti-debug guard by overriding it.

---

## Static-assisted emulation with angr

I stayed in static territory by using angr on the raw binary and hooking `0x2bbd` to always return 0. That keeps the control flow identical while bypassing the timing trap. Here's the full script I ran:

```python
#!/usr/bin/env python3
import angr
from pathlib import Path

proj = angr.Project('Classy', main_opts={'base_addr': 0}, auto_load_libs=False)

class ReturnZero(angr.SimProcedure):
    def run(self):
        return 0

proj.hook(0x2bbd, ReturnZero())

# The lookup table starts at .rodata+0x180 (offset 0x4180 in the file)
data = Path('Classy').read_bytes()
base = 0x4180

flag_bytes = []
for i in range(33):           # 0..32
    table_val = data[base + 6*i]   # every 6th byte is used
    state = proj.factory.call_state(0x2f88, i, 0, table_val)
    simgr = proj.factory.simulation_manager(state)
    simgr.run()
    dead = simgr.deadended[0]
    flag_bytes.append(dead.solver.eval(dead.regs.rax) & 0xff)

print(flag_bytes)
print(bytes(flag_bytes))
```

Notes:
- `main_opts={'base_addr': 0}` tells angr to treat the PIE as if loaded at 0, so my addresses match the `objdump` output.
- `hook(0x2bbd, ReturnZero())` replaces the anti-debug timing stub with a constant-returning SimProcedure.
- `call_state(0x2f88, ...)` creates a state that starts *inside* the helper as if it were called normally.
- `simgr.run()` symbolically executes until the function returns; because everything is concrete here, it reaches a single dead-ended state.
- The return value lives in `RAX`, so I grab that and mask to a byte.

Running this produced:

```
[86, 117, 119, 67, 84, 70, 123, 118, 101, 114, 121, 95, 99, 108, 97, 115, 115, 121, 95, 100, 48, 39, 110, 116, 95, 54, 111, 117, 95, 115, 51, 51, 125]
b"VuwCTF{very_classy_d0'nt_6ou_s33}"
```

Converting the ASCII codes gives the flag straight away.

---

## Verifying (carefully)

I avoided live debugging, but running the binary normally with the recovered flag is safe because the anti-debug checks only trigger when a tracer is attached or the environment is slow/virtualized:

```
./Classy
Enter flag: VuwCTF{very_classy_d0'nt_6ou_s33}
# Correct!
```

Great! I confirmed that the flag was correct: ``VuwCTF{very_classy_d0'nt_6ou_s33}``.

---

## Takeaways

- Anti-debug doesn’t mean “no tooling”, it just nudges you toward static reasoning. Hooking the timing probe in angr was enough to keep the exact arithmetic intact.
- The 6-byte stride in the table was a cute obfuscation; only the first byte mattered for each character.
- When a challenge tells you “static only”, it is definitely in your best interest to trust it! The `/proc` and `ptrace` probes would have ruined a live session.

Thank you for reading my write-up! This was an extremely fun CTF, and I would like to express my appreciation to the organizers for hosting the CTF!

If there’s anything you think I could improve on in future write-ups, please let me know!

Thank you and have a great day!