import os
import sys

def fix_nodriver_utf8():
    """
    Converts nodriver files from Latin-1 / non-UTF-8 bytes to clean UTF-8.
    Converts raw \xb1 byte to valid UTF-8 \xc2\xb1 (±).
    """
    site_packages = [p for p in sys.path if "site-packages" in p]
    target_file = None
    
    for sp in site_packages:
        candidate = os.path.join(sp, "nodriver", "cdp", "network.py")
        if os.path.isfile(candidate):
            target_file = candidate
            break

    if not target_file:
        print("Could not locate nodriver/cdp/network.py in site-packages.")
        return False

    print(f"Reading file: {target_file}")
    
    # Read raw bytes or ISO-8859-1 text
    with open(target_file, "r", encoding="iso-8859-1") as f:
        text = f.read()

    # Ensure coding header is at line 1
    if "coding: utf-8" not in text:
        text = "# -*- coding: utf-8 -*-\n" + text

    # Write back as valid UTF-8
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(text)

    print("Successfully converted nodriver/cdp/network.py to valid UTF-8 encoding!")
    return True

if __name__ == "__main__":
    fix_nodriver_utf8()
