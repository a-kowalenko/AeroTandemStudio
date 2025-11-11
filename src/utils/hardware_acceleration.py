"""
Hardware-Beschleunigung für Video-Encoding
Erkennt automatisch verfügbare Hardware und gibt optimierte FFmpeg-Parameter zurück.
"""
import subprocess
import platform
import threading
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW, CONFIG_DIR


class HardwareAccelerationDetector:
    """Erkennt verfügbare Hardware-Beschleunigung und gibt entsprechende FFmpeg-Parameter zurück"""

    def __init__(self):
        self.system = platform.system()
        self.detected_hw = None
        self.hw_type = None
        self._cache_file = os.path.join(CONFIG_DIR, 'hw_cache.json')
        self._detection_timeout = 2.0  # Maximale Zeit für Hardware-Erkennung
        self._cache_version = 2  # WICHTIG: Erhöhen wenn sich GOP-Parameter ändern!

    def detect_hardware(self):
        """
        Erkennt verfügbare Hardware-Beschleunigung.
        Returns: Dict mit Hardware-Informationen
        """
        if self.detected_hw is not None:
            return self.detected_hw

        # Versuche aus Cache zu laden
        cached_result = self._load_from_cache()
        if cached_result:
            print(f"✓ Hardware aus Cache geladen: {cached_result.get('type', 'unknown')}")
            self.detected_hw = cached_result
            self.hw_type = cached_result.get('type')
            return cached_result

        result = {
            'available': False,
            'type': None,
            'encoder': None,
            'decoder': None,
            'hwaccel': None,
            'device': None
        }

        if self.system == 'Windows':
            result = self._detect_windows_hardware()
        elif self.system == 'Darwin':  # macOS
            result = self._detect_macos_hardware()
        elif self.system == 'Linux':
            result = self._detect_linux_hardware()

        # Cache das Ergebnis
        self._save_to_cache(result)

        self.detected_hw = result
        self.hw_type = result.get('type')
        return result

    def detect_async(self, callback, timeout=None):
        """
        Asynchrone Hardware-Erkennung in eigenem Thread.

        Args:
            callback: Funktion die mit dem Ergebnis aufgerufen wird (result_dict)
            timeout: Maximale Wartezeit in Sekunden (default: self._detection_timeout)
        """
        if timeout is None:
            timeout = self._detection_timeout

        def detection_worker():
            start_time = time.time()
            try:
                result = self.detect_hardware()
                elapsed = time.time() - start_time
                print(f"⏱️ Hardware-Erkennung abgeschlossen in {elapsed:.2f}s")
                callback(result)
            except Exception as e:
                print(f"⚠️ Fehler bei Hardware-Erkennung: {e}")
                # Fallback zu Software-Encoding
                fallback = {
                    'available': False,
                    'type': None,
                    'encoder': None,
                    'decoder': None,
                    'hwaccel': None,
                    'device': None
                }
                callback(fallback)

        thread = threading.Thread(target=detection_worker, daemon=True)
        thread.start()

    def _load_from_cache(self):
        """Lädt Hardware-Info aus Cache-Datei"""
        try:
            if os.path.exists(self._cache_file):
                # Prüfe Alter des Caches (max 7 Tage)
                cache_age = time.time() - os.path.getmtime(self._cache_file)
                if cache_age > 7 * 24 * 3600:  # 7 Tage
                    print("🗑️ Hardware-Cache zu alt, wird neu erkannt")
                    return None

                with open(self._cache_file, 'r') as f:
                    cached_data = json.load(f)

                # Prüfe Cache-Version (wichtig für GOP-Parameter-Updates)
                cached_version = cached_data.get('_cache_version', 1)
                if cached_version < self._cache_version:
                    print(f"🗑️ Hardware-Cache veraltet (v{cached_version} < v{self._cache_version}), wird neu erkannt")
                    return None

                return cached_data
        except Exception as e:
            print(f"⚠️ Fehler beim Laden des Hardware-Cache: {e}")
        return None

    def _save_to_cache(self, result):
        """Speichert Hardware-Info in Cache-Datei"""
        try:
            # Füge Cache-Version hinzu
            result['_cache_version'] = self._cache_version

            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"💾 Hardware-Info gecacht: {result.get('type', 'none')} (v{self._cache_version})")
        except Exception as e:
            print(f"⚠️ Fehler beim Speichern des Hardware-Cache: {e}")
        except Exception as e:
            print(f"⚠️ Fehler beim Speichern des Hardware-Cache: {e}")

    def _detect_windows_hardware(self):
        """Erkennt Hardware-Beschleunigung unter Windows (parallel mit Early-Bailout)"""

        # Parallele GPU-Checks mit ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._check_nvidia_hw): 'nvidia',
                executor.submit(self._check_amd_hw): 'amd',
                executor.submit(self._check_intel_hw): 'intel'
            }

            # Warte auf ersten erfolgreichen Check (Early-Bailout)
            for future in as_completed(futures, timeout=self._detection_timeout):
                try:
                    result = future.result()
                    if result and result.get('available'):
                        # Ersten verfügbaren Encoder gefunden - breche ab
                        print(f"✓ Hardware-Beschleunigung gefunden: {result.get('type')}")
                        return result
                except TimeoutError:
                    print("⚠️ Hardware-Check Timeout")
                    continue
                except Exception as e:
                    print(f"⚠️ Hardware-Check Fehler: {e}")
                    continue

        # Kein Hardware-Encoder gefunden
        return {'available': False, 'type': None}

    def _check_nvidia_hw(self):
        """Prüft NVIDIA NVENC"""
        if self._has_nvidia_gpu() and self._check_nvenc_available():
            return {
                'available': True,
                'type': 'nvidia',
                'encoder': 'h264_nvenc',
                'encoder_hevc': 'hevc_nvenc',
                'decoder': 'h264_cuvid',
                'decoder_hevc': 'hevc_cuvid',
                'hwaccel': 'cuda',
                'device': None,
                'extra_params': ['-preset', 'p4', '-tune', 'hq']
            }
        return None

    def _check_amd_hw(self):
        """Prüft AMD AMF"""
        if self._has_amd_gpu() and self._check_amf_available():
            return {
                'available': True,
                'type': 'amd',
                'encoder': 'h264_amf',
                'encoder_hevc': 'hevc_amf',
                'decoder': None,
                'hwaccel': 'dxva2',
                'device': None,
                'extra_params': ['-usage', 'transcoding', '-quality', 'speed', '-g', '30']
            }
        return None

    def _check_intel_hw(self):
        """Prüft Intel Quick Sync"""
        if self._has_intel_gpu() and self._check_qsv_available():
            return {
                'available': True,
                'type': 'intel',
                'encoder': 'h264_qsv',
                'encoder_hevc': 'hevc_qsv',
                'decoder': 'h264_qsv',
                'decoder_hevc': 'hevc_qsv',
                'hwaccel': 'qsv',
                'device': None,
                'extra_params': [
                    '-global_quality', '23',
                    '-preset', 'medium',
                    '-g', '30',  # GOP-Size für Keyframes
                    '-look_ahead', '0',  # Deaktiviere Look-ahead für Stabilität
                    '-bf', '0'  # Keine B-Frames für bessere Kompatibilität
                ]
            }
        return None

    def _has_nvidia_gpu(self):
        """Prüft ob eine NVIDIA GPU im System vorhanden ist"""
        try:
            # Methode 1: nvidia-smi verwenden
            result = subprocess.run(
                ['nvidia-smi', '-L'],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            if result.returncode == 0 and 'GPU' in result.stdout:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # nvidia-smi not found or timed out: expected if no NVIDIA GPU or driver; try next detection method
            pass

        # Methode 2: WMIC verwenden (Windows Management Instrumentation)
        try:
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                if 'nvidia' in output or 'geforce' in output or 'quadro' in output or 'rtx' in output:
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return False

    def _has_amd_gpu(self):
        """Prüft ob eine AMD GPU im System vorhanden ist"""
        try:
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                if 'amd' in output or 'radeon' in output or 'ati' in output:
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # If WMIC is not available or times out, assume AMD GPU is not present.
            pass

        return False

    def _has_intel_gpu(self):
        """Prüft ob eine Intel GPU im System vorhanden ist"""
        try:
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                if 'intel' in output or 'uhd graphics' in output or 'iris' in output or 'hd graphics' in output:
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # If WMIC is not available or times out, assume no Intel GPU is present.
            pass

        return False

    def _detect_macos_hardware(self):
        """Erkennt Hardware-Beschleunigung unter macOS (VideoToolbox)"""
        if self._check_videotoolbox_available():
            return {
                'available': True,
                'type': 'videotoolbox',
                'encoder': 'h264_videotoolbox',
                'encoder_hevc': 'hevc_videotoolbox',
                'decoder': None,
                'hwaccel': 'videotoolbox',
                'device': None,
                'extra_params': ['-b:v', '0', '-g', '30']  # VBR mode + GOP
            }

        return {'available': False, 'type': None}

    def _detect_linux_hardware(self):
        """Erkennt Hardware-Beschleunigung unter Linux"""
        # Priorität: NVIDIA NVENC > VAAPI

        # 1. Prüfe NVIDIA NVENC (nur wenn NVIDIA GPU vorhanden)
        if self._has_nvidia_gpu_linux() and self._check_nvenc_available():
            return {
                'available': True,
                'type': 'nvidia',
                'encoder': 'h264_nvenc',
                'encoder_hevc': 'hevc_nvenc',
                'decoder': 'h264_cuvid',
                'decoder_hevc': 'hevc_cuvid',
                'hwaccel': 'cuda',
                'device': None,
                'extra_params': ['-preset', 'p4', '-tune', 'hq', '-g', '30']
            }

        # 2. Prüfe VAAPI (Intel/AMD unter Linux)
        if self._check_vaapi_available():
            return {
                'available': True,
                'type': 'vaapi',
                'encoder': 'h264_vaapi',
                'encoder_hevc': 'hevc_vaapi',
                'decoder': None,
                'hwaccel': 'vaapi',
                'device': '/dev/dri/renderD128',
                'extra_params': ['-g', '30']
            }

        return {'available': False, 'type': None}

    def _has_nvidia_gpu_linux(self):
        """Prüft ob eine NVIDIA GPU unter Linux vorhanden ist"""
        try:
            # nvidia-smi verwenden
            result = subprocess.run(
                ['nvidia-smi', '-L'],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0 and 'GPU' in result.stdout:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # lspci verwenden
        try:
            result = subprocess.run(
                ['lspci'],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                if 'nvidia' in output and ('vga' in output or '3d' in output):
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # It's safe to ignore these exceptions: if lspci is not available or times out,
            # we simply assume no NVIDIA GPU is present and return False.
            pass

        return False

    def _check_nvenc_available(self):
        """Prüft ob NVIDIA NVENC verfügbar ist (nur Encoder-Liste, kein Init-Test)"""
        try:
            # Nur prüfen ob Encoder in FFmpeg verfügbar ist
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            return 'h264_nvenc' in result.stdout
        except:
            return False

    def _check_amf_available(self):
        """Prüft ob AMD AMF verfügbar ist (nur Encoder-Liste, kein Init-Test)"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            return 'h264_amf' in result.stdout
        except Exception:
            return False

    def _check_qsv_available(self):
        """Prüft ob Intel Quick Sync verfügbar ist (nur Encoder-Liste, kein Init-Test)"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            return 'h264_qsv' in result.stdout
        except:
            return False

    def _check_videotoolbox_available(self):
        """Prüft ob VideoToolbox (macOS) verfügbar ist"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            return 'h264_videotoolbox' in result.stdout
        except Exception:
            return False

    def _check_vaapi_available(self):
        """Prüft ob VAAPI (Linux) verfügbar ist"""
        try:
            # Prüfe ob /dev/dri/renderD128 existiert
            import os
            if not os.path.exists('/dev/dri/renderD128'):
                return False

            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return 'h264_vaapi' in result.stdout
        except Exception:
            return False

    def get_encoding_params(self, codec='h264', enable_hw_accel=True):
        """
        Gibt optimierte Encoding-Parameter für die erkannte Hardware zurück.

        Args:
            codec: 'h264' oder 'hevc'
            enable_hw_accel: Ob Hardware-Beschleunigung verwendet werden soll

        Returns:
            Dict mit FFmpeg-Parametern
        """
        if not enable_hw_accel:
            return self._get_software_params(codec)

        hw_info = self.detect_hardware()

        if not hw_info['available']:
            return self._get_software_params(codec)

        params = {
            'input_params': [],
            'output_params': [],
            'encoder': None
        }

        # Hardware Decoder (für Input)
        if hw_info['hwaccel']:
            params['input_params'].extend(['-hwaccel', hw_info['hwaccel']])

            if hw_info['device']:
                params['input_params'].extend(['-hwaccel_device', hw_info['device']])

        # Hardware Encoder (für Output)
        if codec in ['hevc', 'h265'] and 'encoder_hevc' in hw_info:
            params['encoder'] = hw_info['encoder_hevc']
        else:
            params['encoder'] = hw_info['encoder']

        # Codec-spezifische Parameter
        if params['encoder']:
            params['output_params'].extend(['-c:v', params['encoder']])

            # Extra Parameter für bessere Qualität
            if hw_info.get('extra_params'):
                params['output_params'].extend(hw_info['extra_params'])

        return params

    def _get_software_params(self, codec='h264'):
        """Gibt Software-Encoding-Parameter zurück (Fallback)"""
        # Encoder-Mapping
        encoder_map = {
            'h264': 'libx264',
            'h265': 'libx265',
            'hevc': 'libx265',
            'vp9': 'libvpx-vp9',
            'av1': 'libaom-av1'  # Oder 'libsvtav1' für schnelleres Encoding
        }

        encoder = encoder_map.get(codec, 'libx264')

        # Basis-Parameter
        params = {
            'input_params': [],
            'output_params': ['-c:v', encoder],
            'encoder': encoder
        }

        # Codec-spezifische Optimierungen
        if codec in ['h264', 'h265', 'hevc']:
            params['output_params'].extend([
                '-preset', 'medium',
                '-crf', '23'
            ])
        elif codec == 'vp9':
            params['output_params'].extend([
                '-b:v', '0',  # Constant Quality Mode
                '-crf', '31',  # Qualität (0-63, 31 ist gut)
                '-cpu-used', '2'  # Geschwindigkeit (0=langsam, 5=schnell)
            ])
        elif codec == 'av1':
            params['output_params'].extend([
                '-b:v', '0',  # Constant Quality Mode
                '-crf', '32',  # Qualität (0-63)
                '-cpu-used', '4'  # Geschwindigkeit (0=langsam, 8=schnell)
            ])

        return params

    def get_hardware_info_string(self, codec='h264'):
        """
        Gibt einen lesbaren String mit Hardware-Informationen zurück

        Args:
            codec: Der Codec für den der Encoder angezeigt werden soll (z.B. 'h264', 'h265', 'hevc')

        Returns:
            String wie "NVIDIA NVENC (Encoder: hevc_nvenc)" oder "Keine Hardware-Beschleunigung verfügbar"
        """
        hw_info = self.detect_hardware()

        if not hw_info['available']:
            return "Keine Hardware-Beschleunigung verfügbar"

        hw_names = {
            'nvidia': 'NVIDIA NVENC',
            'amd': 'AMD AMF',
            'intel': 'Intel Quick Sync',
            'videotoolbox': 'Apple VideoToolbox',
            'vaapi': 'VAAPI'
        }

        hw_name = hw_names.get(hw_info['type'], hw_info['type'])

        # Wähle den richtigen Encoder basierend auf Codec
        if codec in ['hevc', 'h265'] and 'encoder_hevc' in hw_info:
            encoder = hw_info.get('encoder_hevc', 'unknown')
        else:
            encoder = hw_info.get('encoder', 'unknown')

        return f"{hw_name} (Encoder: {encoder})"
