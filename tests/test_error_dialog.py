"""
Test-Skript für den Error-Dialog mit verschiedenen Text-Längen
"""
import tkinter as tk
from src.gui.components.error_dialog import show_error_dialog


def test_short_details():
    """Test mit kurzen Details"""
    root = tk.Tk()
    root.geometry("600x400")
    root.title("Test Root Window")

    def show_short():
        show_error_dialog(
            root,
            title="SD-Karte entfernt",
            message="Die SD-Karte wurde während der Auswahl entfernt.",
            details=[
                "Kurzer Text",
                "Noch ein kurzer Text"
            ]
        )

    tk.Button(root, text="Kurze Details", command=show_short, padx=20, pady=10).pack(pady=20)
    root.mainloop()


def test_long_details():
    """Test mit langen Details (Textumbruch)"""
    root = tk.Tk()
    root.geometry("600x400")
    root.title("Test Root Window")

    def show_long():
        show_error_dialog(
            root,
            title="SD-Karte entfernt",
            message="Die SD-Karte wurde während der Auswahl entfernt.\n\nDer Dialog wird geschlossen.",
            details=[
                "Bitte stecken Sie die SD-Karte wieder ein und versuchen Sie es erneut.",
                "Dies ist ein sehr langer Text der mehrere Zeilen benötigen wird und deshalb umbrechen sollte wenn er das Ende des Frames erreicht.",
                "Noch ein sehr langer Text mit vielen Wörtern die dafür sorgen dass der Text umgebrochen werden muss damit alles sichtbar ist.",
                "Kurzer Text dazwischen",
                "Und noch ein extrem langer Text der demonstriert dass der Details-Frame automatisch in der Höhe wächst wenn mehr Text vorhanden ist und alles korrekt angezeigt werden soll ohne dass etwas abgeschnitten wird."
            ]
        )

    tk.Button(root, text="Lange Details (mit Umbruch)", command=show_long, padx=20, pady=10).pack(pady=20)
    root.mainloop()


def test_many_details():
    """Test mit vielen Details"""
    root = tk.Tk()
    root.geometry("600x400")
    root.title("Test Root Window")

    def show_many():
        show_error_dialog(
            root,
            title="Fehler beim Importieren",
            message="Mehrere Fehler sind aufgetreten:",
            details=[
                f"Detail {i}: Dies ist Detail Nummer {i} von vielen" for i in range(1, 11)
            ]
        )

    tk.Button(root, text="Viele Details", command=show_many, padx=20, pady=10).pack(pady=20)
    root.mainloop()


def test_all():
    """Zeigt alle Tests in einem Fenster"""
    root = tk.Tk()
    root.geometry("600x400")
    root.title("Error Dialog Tests")

    tk.Label(root, text="Error Dialog Tests", font=("Arial", 16, "bold")).pack(pady=20)
    tk.Label(root, text="Dialoge erscheinen direkt zentriert ohne Flackern!",
             font=("Arial", 9), fg="#666").pack(pady=5)

    def show_short():
        show_error_dialog(
            root,
            title="Kurzer Fehler",
            message="Eine kurze Fehlermeldung.",
            details=["Detail 1", "Detail 2"]
        )

    def show_long():
        show_error_dialog(
            root,
            title="SD-Karte entfernt",
            message="Die SD-Karte wurde während der Auswahl entfernt.\n\nDer Dialog wird geschlossen.",
            details=[
                "Bitte stecken Sie die SD-Karte wieder ein und versuchen Sie es erneut.",
                "Dies ist ein sehr langer Text der mehrere Zeilen benötigen wird und deshalb umbrechen sollte wenn er das Ende des Frames erreicht.",
                "Noch ein sehr langer Text mit vielen Wörtern die dafür sorgen dass der Text umgebrochen werden muss damit alles sichtbar ist.",
                "Kurzer Text dazwischen",
                "Und noch ein extrem langer Text der demonstriert dass der Details-Frame automatisch in der Höhe wächst."
            ]
        )

    def show_many():
        show_error_dialog(
            root,
            title="Viele Fehler",
            message="Mehrere Fehler sind aufgetreten:",
            details=[f"Fehler {i}: Detail Nummer {i}" for i in range(1, 12)]
        )

    def show_no_details():
        show_error_dialog(
            root,
            title="Einfacher Fehler",
            message="Ein Fehler ist aufgetreten.\n\nKeine weiteren Details verfügbar."
        )

    tk.Button(root, text="1. Kurze Details", command=show_short, width=30, pady=5).pack(pady=5)
    tk.Button(root, text="2. Lange Details (Textumbruch)", command=show_long, width=30, pady=5).pack(pady=5)
    tk.Button(root, text="3. Viele Details", command=show_many, width=30, pady=5).pack(pady=5)
    tk.Button(root, text="4. Keine Details", command=show_no_details, width=30, pady=5).pack(pady=5)

    root.mainloop()


if __name__ == "__main__":
    test_all()

