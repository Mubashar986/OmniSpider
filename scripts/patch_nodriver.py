import os
import sys

def patch_nodriver_network():
    """
    Explicitly converts nodriver/cdp/network.py to clean UTF-8 encoding.
    Resolves Python 3.14 strict PEP 263 non-ASCII docstring byte issues.
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

    print(f"Targeting file: {target_file}")
    
    # Read raw bytes
    with open(target_file, "rb") as f:
        raw_bytes = f.read()

    # Check if header is already present
    header = b"# -*- coding: utf-8 -*-\n"
    if not raw_bytes.startswith(header):
        new_bytes = header + raw_bytes
        with open(target_file, "wb") as f:
            f.write(new_bytes)
        print("Successfully added UTF-8 encoding header to nodriver/cdp/network.py!")
    else:
        print("Encoding header already present.")
        
    return True

if __name__ == "__main__":
    patch_nodriver_network()
