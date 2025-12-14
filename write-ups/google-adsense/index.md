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

## Making the disk image usable (VHD -> raw, find the NTFS)

I used Sleuthkit tools (`fls`, `tsk_recover`, `icat`) since they are perfect for analyzing raw disks.

1) Identify the container  
   ```
   file 'evidence.vhd'
   # Microsoft Disk Image ... ~500MB
   ```
   So it’s a VHD (VPC format) with ~500 MB capacity.

2) Convert to raw  
   ```
   qemu-img convert -O raw 'evidence.vhd' evidence.raw
   ```
   Now I have `evidence.raw`.

3) Inspect the partition table  
   ```
   mmls evidence.raw
   # ...
   # 002: 000:000 0000000128 0001021951 0001021824 NTFS / exFAT (0x07)
   ```
   The NTFS partition begins at sector 128. Sleuthkit takes offsets in sectors, so `-o 128` is the magic number for every command.

---

## Listing and carving the Resumes directory (with ADS)

The goal here: only extract the Resumes folder instead of the whole filesystem becuase the rest is irrelevant.

1) Find the directory entry  
   ```
   fls -o 128 evidence.raw | rg -i 'resumes'
   # d/d 38-144-5: Resumes
   ```
   That `38-144-5` is the NTFS MFT reference for the Resumes directory.

2) Peek inside Resumes to see what’s there  
   ```
   fls -o 128 evidence.raw 38-144-5
   ```
   Output: dozens of `GoogleAds*.pdf` plus a ton of NTFS Alternate Data Streams (ADS) entries like `:flag.txt`, `:info.json`, random `.txt` stream names, and one suspicious `:hireme.jxl`.

3) Recover only that directory (normal files)  
   ```
   mkdir recovered
   tsk_recover -a -o 128 -d 38 evidence.raw recovered
   ```
   This recovers the normal files (PDFs, archives, etc). **Sleuthkit doesn’t automatically dump ADS streams here**, so I extracted ADS separately using `fls` + `icat`.

4) Dump ADS streams  
   ```
   mkdir ads
   fls -o 128 evidence.raw 38-144-5 | rg '\\.pdf:' | awk '{print $2, $3}' | while read -r inode name; do
     inode=${inode%:}
     icat -o 128 evidence.raw "$inode" > "ads/$name"
   done
   ```
   Now `ads/` contains files with names like `GoogleAdsAnalystResume.pdf:flag.txt`.

---

## First sweep: obvious flags and decoys

With all ADS dumped into `ads/`, I searched for flag-looking strings.

```
rg -a "nite\\{" ads
```

What did I find? (hint: not the real flag):
- Every `:flag.txt` stream on the PDFs contained the same fake flag: `nite{1ma0_br0_r3lly_th0ught}`.
- One stray ADS (`GoogleAdsKeeperResume.pdf:abxu07mnid.txt`) had `nite{us3l3ss_but_y0u_n3v3r_kn0w}`. Still a decoy... but it was interesting that it was exactly 32 characters long.

Well, this means I gotta dig deeper.

---

## Focusing on the interesting résumé: the “Specialist”

While listing ADS, one stood out:
- `GoogleAdsSpecialistResume.pdf:hireme.jxl`

Despite the `.jxl` extension, this file is actually an **OLE document with VBA macros** (like a Word-style macro container). I used `olevba` / `pcodedmp` to extract the code and deobfuscate it.

Tracing the macro logic showed:
- It pulls several short strings out of other ADS streams (base64 fragments), concatenates them, and base64-decodes them into ciphertext.
- It also reads a 32-byte “key” from `GoogleAdsKeeperResume.pdf:abxu07mnid.txt` (the “fake flag” from earlier).
- Decrypting that ciphertext with **AES-256-CBC** (IV = 16 null bytes) produces a URL:
  `https://github.com/adsensenite/adsensetoken/releases/download/v7/adsense_token.exe`

At that point, the macro would download the EXE. I just grabbed it directly from the recovered URL instead.

---

## Analysis of `adsense_token.exe`

This EXE is a little “AdSense funds viewer” GUI that asks you to enter an AdSense token.
- The important part: the EXE **doesn’t ship the real flag directly**. Instead, it validates your input, then uses your input token as a key to decrypt another embedded stage.

I reversed the token validation and found:
- The token format is `pub-` + 16 digits.
- The binary has a hard-coded MD5 it wants to match, plus some extra digit constraints (which makes brute forcing feasible).

After brute forcing with those constraints, the valid token was:
`pub-2706080128070709`

Once you have the correct token, you can use it to decrypt the embedded blob:
- There’s a 402-byte blob at file offset `0xB8588`.
- The EXE XORs that blob with the token bytes (repeating) to produce a `cmd.exe /c ...` command line.
- Inside that command line is a PowerShell `-enc <base64>` payload.

Instead of running anything, I just reproduced the decryption and base64 decoding in Python and got:
`echo nite{1n_th1s_ultr4_4w3s0m3_p3rf3ct_w0rld_w1ll_th3r3_st1ll_b3_ADS_4nd_UAC_BYPASS?} | Out-File C:\\temp\\flag.txt; ...`

So the flag was right there in the decoded PowerShell payload! The final flag is: `nite{1n_th1s_ultr4_4w3s0m3_p3rf3ct_w0rld_w1ll_th3r3_st1ll_b3_ADS_4nd_UAC_BYPASS?}`!

---

## Takeaways
- Converting container formats early makes forensics tooling painless.
- NTFS Alternate Data Streams are where the fun lives! Always list ADS (`fls`) and extract them (`icat`).

Thank you for reading my write-up! I enjoyed playing in this CTF, and I loved the challenges and would like to express my appreciation to the organizers for hosting the CTF!

If there’s anything you think I could improve on in future write-ups, please let me know!

Thank you and have a great day!