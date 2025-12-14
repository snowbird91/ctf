---
layout: post
title: "Google ADSense"
categories: [forensics, nitectf2025]
date: 2025-12-14 12:00:00 -0500
writeup: true
permalink: /write-ups/google-adsense/
order: 14
---

**niteCTF 2025**

I played niteCTF 2025 with tjcsc. We got 1st place!

**Challenge:** Google ADSense  
**Category:** Forensics  
**Authors:** tryhard | Indrath  
**Flag:** ``nite{1n_th1s_ultr4_4w3s0m3_p3rf3ct_w0rld_w1ll_th3r3_st1ll_b3_ADS_4nd_UAC_BYPASS?}``

---

## My initial read / first impressions

- The description mentioned something about “$11.48 AdSense revenue” and said everything lived in a **Resumes** directory. One of the organizers said that "nope, no challenge requires you to put any names in the flag". This might be useful for avoiding rabbit holes in the future...
- Given only `evidence.vhd`, this challenge felt like a disk image treasure hunt of some sort. My plan was to first make the image usable, then dig further for anything useful. 

---

## Making the disk image usable (VHD → raw, find the NTFS)

I used Sleuthkit tools (`fls`, `tsk_recover`, `icat`) since they are perfect for analyzing raw disks.

1) Identify the container  
   ```
   file 'evidence.vhd'
   # Microsoft Disk Image ... 524288000 bytes
   ```
   So it’s a VHD (VPC format) with ~500 MB capacity.

2) Convert to raw  
   ```
   qemu-img convert -O raw 'evidence.vhd' evidence.raw
   ```
   Now I have `evidence.raw` (500 MB).

3) Inspect the partition table  
   ```
   fdisk -l evidence.raw
   # evidence.raw1  Start=128  End=1021951  Type=7 (NTFS)
   ```
   The NTFS partition begins at sector 128. Sleuthkit takes sector offsets in sectors, so `-o 128` is the magic number for every command.

4) Optional confirmation with Sleuthkit  
   ```
   mmls evidence.raw
   # shows one NTFS volume starting at 128 (same as fdisk)
   ```

---

## Listing and carving the Resumes directory (with ADS)

The goal here: only extract the Resumes folder instead of the whole filesystem becuase the rest is irrelevant.

1) Find the directory entry  
   ```
   fls -o 128 evidence.raw | rg -i 'resumes'
   # d/d 38-144-5: Resumes
   # d/d 138-144-5: Old_Resumes
   ```
   That `38-144-5` is the NTFS MFT reference for the Resumes directory.

2) Peek inside Resumes to see what’s there  
   ```
   fls -o 128 evidence.raw 38-144-5
   ```
   Output: dozens of `GoogleAds*.pdf` plus many ADS entries (`:flag.txt`, `:info.json`, `:metadata.txt`, random `.txt` stream names). There were also a few zip bundles like `Resume_Package_3.zip`.

3) Recover only that directory (including ADS)  
   ```
   mkdir recovered
   tsk_recover -a -o 128 -d 38 evidence.raw recovered
   ```
   `-a` keeps allocated files only; `-d 38` scopes to the Resumes folder; ADS are emitted as filenames containing colons (Linux handles that fine).

---

## First sweep: obvious flags and decoys

With everything in `recovered/`, I searched for flag-looking strings.

``+
rg -a "nite{" recovered
+```

What did I find? (hint: not the real flag):
- Every `flag.txt` stream on the PDFs contained the same fake flag: `nite{1ma0_br0_r3lly_th0ught}`.
- One stray ADS (`GoogleAdsKeeperResume.pdf:abxu07mnid.txt`) had `nite{us3l3ss_but_y0u_n3v3r_kn0w}`, another fake flag :(

Well, this means I gotta dig deeper.

---

## Focusing on the interesting résumé: the “Specialist”

While listing ADS, one stood out:
- `GoogleAdsSpecialistResume.pdf:hireme.jxl`

Despite the `.jxl` extension, the bytes were a ZIP. Unzipping it produced a macro-enabled document (VBA) with heavy obfuscation (lots of `vdySPCEKzGniHf(Array(...), Array(...))` gibberish). Tracing the deobfuscated logic showed:
- It builds a download/execute chain that writes **`adsense_token.exe`** to `%TEMP%`.
- It uses the AdSense publisher ID literal `pub-2706080128070709` as a “token” to feed the EXE.

Conveniently, one of the bundled zip files (`Resume_Package_3.zip`) contained a tiny git repo `adsensetoken_repo/` with the same `adsense_token.exe` and a README that simply said “the token.” That gave us the exact binary without touching the macro.

---

## Analysis of `adsense_token.exe`

Running `strings` was unhelpful, so I looked for embedded blobs:
- I found a ~402-byte chunk around offset `0xB8588` looked like encrypted data.
- The program asks for a token (from the macro, we know it’s `pub-2706080128070709`).
- Reversing the code path showed it XORs that blob with the token bytes (repeating) to build a command line, then runs `cmd.exe /c ...` containing a PowerShell `-enc <base64>` payload.

Rather than reversing every function, I just replicated that decryption in Python:

```python
import pathlib, base64
exe = pathlib.Path("adsense_token.exe").read_bytes()
blob = exe[0xB8588:0xB8588+402]
key = b"pub-2706080128070709"
cmd = bytes(b ^ key[i % len(key)] for i, b in enumerate(blob)).decode("utf-8", "replace")
enc = cmd.split("-enc ")[1].split('"')[0]
print(base64.b64decode(enc).decode())
```

The decoded PowerShell payload literally echoes the flag to `C:\temp\flag.txt`. `nite{1n_th1s_ultr4_4w3s0m3_p3rf3ct_w0rld_w1ll_th3r3_st1ll_b3_ADS_4nd_UAC_BYPASS?}` was inside flag.txt! Great, we found the flag!

---

## Takeaways

- Converting container formats early makes forensics tooling painless. 
- In some cases, NTFS Alternate Data Streams are where the fun lives! Always list ADS (`fls`) and recover them (`tsk_recover`).

Thank you for reading my write-up! I enjoyed playing in this CTF, and I loved the challenges and would like to express my appreciation to the organizers for hosting the CTF!

If there’s anything you think I could improve on in future write-ups, please let me know!

Thank you and have a great day!
