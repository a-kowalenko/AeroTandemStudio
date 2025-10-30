import os
import sys
import subprocess

level = "build"
if len(sys.argv) > 1:
    level = sys.argv[1].lower()

os.environ["BUILD_LEVEL"] = level

subprocess.run(["pyinstaller", "Aero Tandem Studio.spec"], check=True)