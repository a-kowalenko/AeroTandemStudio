#!/usr/bin/env python3
"""
Hauptstartskript für den Tandem Video Generator
"""

import os
import sys

# Füge den src Ordner zum Python-Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.gui.app import VideoGeneratorApp

def main():
    """Hauptfunktion der Anwendung"""
    try:
        app = VideoGeneratorApp()
        app.run()
    except Exception as e:
        print(f"Fehler beim Starten der Anwendung: {e}")
        input("Drücke Enter zum Beenden...")

if __name__ == "__main__":
    main()