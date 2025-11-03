"""
Paralleles Video-Processing Modul
Ermöglicht gleichzeitiges Encoding mehrerer Videos für bessere Performance auf Multi-Core-Systemen
"""
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
import os


class ParallelVideoProcessor:
    """
    Erweitert VideoProcessor um parallele Verarbeitungsfähigkeiten.

    Vorteile:
    - Mehrere Videos werden gleichzeitig enkodiert
    - Optimale Auslastung von Multi-Core-CPUs
    - Besonders effektiv bei Hardware-Beschleunigung
    """

    def __init__(self, hw_accel_enabled=False):
        self.hw_accel_enabled = hw_accel_enabled
        self.max_workers = self._calculate_optimal_workers()

    def _calculate_optimal_workers(self):
        """
        Berechnet die optimale Anzahl von Worker-Threads für paralleles Video-Encoding.

        Berücksichtigt:
        - CPU-Kerne
        - Hardware-Beschleunigung (mehr Threads möglich)
        - Sicherheitsmargen (nicht alle Kerne nutzen)
        """
        cpu_count = multiprocessing.cpu_count()

        if self.hw_accel_enabled:
            # Mit Hardware-Beschleunigung: Mehr parallele Jobs möglich
            # da GPU das Encoding übernimmt
            workers = min(cpu_count, 4)  # Max 4 parallele Hardware-Encodings
            print(f"🚀 Paralleles Processing: {workers} Worker-Threads (Hardware-Encoding, {cpu_count} CPU-Kerne)")
        else:
            # Software-Encoding: Konservativer
            # Jeder FFmpeg-Prozess nutzt bereits mehrere Threads
            workers = max(1, cpu_count // 2)  # Halbe CPU-Kerne
            print(f"🚀 Paralleles Processing: {workers} Worker-Threads (Software-Encoding, {cpu_count} CPU-Kerne)")

        return workers

    def process_videos_parallel(self, video_tasks, cancel_event=None):
        """
        Verarbeitet mehrere Videos parallel mit ThreadPoolExecutor.

        Args:
            video_tasks: Liste von Tuples (task_function, args, kwargs)
            cancel_event: Optional threading.Event für Abbruch

        Returns:
            Liste der Ergebnisse in der Reihenfolge der Fertigstellung
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Starte alle Tasks
            futures = {}
            for i, (task_func, args, kwargs) in enumerate(video_tasks):
                future = executor.submit(task_func, *args, **kwargs)
                futures[future] = i

            # Sammle Ergebnisse in der Reihenfolge ihrer Fertigstellung
            for future in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    # Abbruch angefordert - verwerfe verbleibende Tasks
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise Exception("Parallele Verarbeitung abgebrochen")

                task_index = futures[future]
                try:
                    result = future.result()
                    results.append((task_index, result, None))
                    print(f"✓ Video-Task {task_index + 1}/{len(video_tasks)} abgeschlossen")
                except Exception as e:
                    results.append((task_index, None, e))
                    print(f"✗ Video-Task {task_index + 1}/{len(video_tasks)} fehlgeschlagen: {e}")

        # Sortiere Ergebnisse nach ursprünglicher Reihenfolge
        results.sort(key=lambda x: x[0])
        return results

    def get_worker_info(self):
        """Gibt Informationen über die Worker-Konfiguration zurück"""
        return {
            'max_workers': self.max_workers,
            'cpu_count': multiprocessing.cpu_count(),
            'hw_accel_enabled': self.hw_accel_enabled
        }

