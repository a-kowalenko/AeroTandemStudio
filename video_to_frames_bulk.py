import cv2
import os
import argparse


def process_all_videos(input_dir, output_root, fps_rate=1.0):
    if not os.path.exists(input_dir):
        print(f"❌ Fehler: Der Input-Ordner '{input_dir}' existiert nicht.")
        return

    # Unterstützte Video-Formate
    valid_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.3gp', '.m4v')

    # Alle Dateien im Ordner auflisten und filtern
    video_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)]

    if not video_files:
        print(f"⚠ Keine passenden Videos im Ordner '{input_dir}' gefunden.")
        return

    print(f"=== Großauftrag gestartet: {len(video_files)} Videos gefunden ===")
    print(f"Ziel-FPS: {fps_rate} Frame(s) pro Sekunde\n")

    for idx, video_name in enumerate(video_files, 1):
        video_path = os.path.join(input_dir, video_name)
        base_name = os.path.splitext(video_name)[0]

        # Für jedes Video einen eigenen Unterordner im Output-Ordner anlegen
        video_output_dir = os.path.join(output_root, base_name)
        os.makedirs(video_output_dir, exist_ok=True)

        print(f"[{idx}/{len(video_files)}] Verarbeite: {video_name}")

        # OpenCV Video-Kontext öffnen
        video = cv2.VideoCapture(video_path)
        video_fps = video.get(cv2.CAP_PROP_FPS)
        total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))

        if video_fps == 0:
            print(f"❌ Fehler: Konnte FPS für {video_name} nicht lesen. Überspringe...")
            continue

        frame_step = int(video_fps / fps_rate)
        if frame_step < 1:
            frame_step = 1

        frame_count = 0
        saved_count = 0

        while frame_count < total_frames:
            video.set(cv2.CAP_PROP_POS_FRAMES, frame_count)
            success, frame = video.read()

            if not success:
                break

            current_second = frame_count / video_fps
            file_name = f"{base_name}_sec_{current_second:06.2f}.jpg"
            file_path = os.path.join(video_output_dir, file_name)

            # Bild abspeichern
            cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            saved_count += 1
            frame_count += frame_step

        video.release()
        print(f"   -> Fertig! {saved_count} Bilder extrahiert nach: {video_output_dir}\n")

    print("✅ Alle Videos erfolgreich verarbeitet!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extrahiert Frames aus ALLEN Videos eines Ordners für das KI-Training.")

    parser.add_argument("-i", "--input", required=True, help="Ordner mit den Rohvideos")
    parser.add_argument("-o", "--output", required=True, help="Hauptordner für die extrahierten Bilder")
    parser.add_argument("-f", "--fps", type=float, default=1.0, help="Frames pro Sekunde (Standard: 1.0)")

    args = parser.parse_args()

    process_all_videos(args.input, args.output, args.fps)