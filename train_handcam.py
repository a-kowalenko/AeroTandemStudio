#!/usr/bin/env python3
"""Abwärtskompatibel – delegiert an train_photo_classifier.py."""

from train_photo_classifier import main

if __name__ == "__main__":
    import sys

    if "--camera" not in sys.argv:
        sys.argv.extend(["--camera", "handcam"])
    main()
