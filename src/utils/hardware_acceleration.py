"""
Hardware-Beschleunigung für Video-Encoding
Erkennt automatisch verfügbare Hardware und gibt optimierte FFmpeg-Parameter zurück.
"""
import subprocess
import platform
import os
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


class HardwareAccelerationDetector:
    """Erkennt verfügbare Hardware-Beschleunigung und gibt entsprechende FFmpeg-Parameter zurück"""

    def __init__(self):
        self.system = platform.system()
        self.detected_hw = None
        self.hw_type = None

    def detect_hardware(self):
        """
        Erkennt verfügbare Hardware-Beschleunigung.
        Returns: Dict mit Hardware-Informationen
        """
        if self.detected_hw is not None:
            return self.detected_hw

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

        self.detected_hw = result
        self.hw_type = result.get('type')
        return result

    def _detect_windows_hardware(self):
        """Erkennt Hardware-Beschleunigung unter Windows"""
        # Priorität: NVIDIA NVENC > AMD AMF > Intel Quick Sync

        # 1. Prüfe NVIDIA NVENC
        if self._check_nvenc_available():
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

        # 2. Prüfe AMD AMF
        if self._check_amf_available():
            return {
                'available': True,
                'type': 'amd',
                'encoder': 'h264_amf',
                'encoder_hevc': 'hevc_amf',
                'decoder': None,
                'hwaccel': 'dxva2',
                'device': None,
                'extra_params': ['-usage', 'transcoding', '-quality', 'speed']
            }

        # 3. Prüfe Intel Quick Sync
        if self._check_qsv_available():
            return {
                'available': True,
                'type': 'intel',
                'encoder': 'h264_qsv',
                'encoder_hevc': 'hevc_qsv',
                'decoder': 'h264_qsv',
                'decoder_hevc': 'hevc_qsv',
                'hwaccel': 'qsv',
                'device': None,
                'extra_params': ['-preset', 'medium', '-look_ahead', '1']
            }

        return {'available': False, 'type': None}

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
                'extra_params': ['-b:v', '0']  # VBR mode
            }

        return {'available': False, 'type': None}

    def _detect_linux_hardware(self):
        """Erkennt Hardware-Beschleunigung unter Linux"""
        # Priorität: NVIDIA NVENC > VAAPI

        # 1. Prüfe NVIDIA NVENC
        if self._check_nvenc_available():
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
                'extra_params': []
            }

        return {'available': False, 'type': None}

    def _check_nvenc_available(self):
        """Prüft ob NVIDIA NVENC verfügbar ist und funktionsfähig"""
        try:
            # Prüfe ob Encoder in FFmpeg verfügbar ist
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            if 'h264_nvenc' not in result.stdout:
                return False

            # Zusätzlicher Test: Versuche tatsächlich den Encoder zu initialisieren
            # Dies erkennt Treiber-Probleme frühzeitig
            test_result = subprocess.run(
                ['ffmpeg', '-f', 'lavfi', '-i', 'nullsrc=s=256x256:d=0.1',
                 '-c:v', 'h264_nvenc', '-f', 'null', '-'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            # Prüfe auf Treiber-Fehler
            if test_result.returncode != 0:
                stderr = test_result.stderr.lower()
                if 'driver does not support' in stderr or 'nvenc api version' in stderr:
                    print("⚠️ NVENC gefunden, aber Treiber zu alt oder nicht kompatibel")
                    print("   Hinweis: Aktualisieren Sie Ihren NVIDIA-Treiber auf Version 570.0+")
                    return False
                # Andere Fehler ignorieren (könnten false positives sein)

            return True

        except:
            return False

    def _check_amf_available(self):
        """Prüft ob AMD AMF verfügbar ist und funktionsfähig"""
        try:
            # Prüfe ob Encoder in FFmpeg verfügbar ist
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            if 'h264_amf' not in result.stdout:
                return False

            # Zusätzlicher Test: Versuche tatsächlich den Encoder zu initialisieren
            # Teste mit minimalen Parametern (keine extra params)
            test_result = subprocess.run(
                ['ffmpeg', '-f', 'lavfi', '-i', 'nullsrc=s=256x256:d=0.1',
                 '-c:v', 'h264_amf',
                 '-f', 'null', '-'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            # Prüfe auf Encoder-Fehler
            if test_result.returncode != 0:
                stderr = test_result.stderr.lower()
                amf_errors = [
                    'could not open encoder',
                    'unable to parse option',
                    'error setting option',
                    'amf encoder error',
                    'no device found',
                    'amf context not initialized'
                ]

                if any(err in stderr for err in amf_errors):
                    print("⚠️ AMF Encoder gefunden, aber nicht funktionsfähig")
                    print("   Mögliche Gründe: Treiber zu alt, GPU nicht kompatibel, oder AMD-Software fehlt")
                    return False
                # Andere Fehler ignorieren

            return True

        except:
            return False

    def _check_qsv_available(self):
        """Prüft ob Intel Quick Sync verfügbar ist"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5,
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
        except:
            return False

    def _check_vaapi_available(self):
        """Prüft ob VAAPI (Linux) verfügbar ist"""
        try:
            # Prüfe ob /dev/dri/renderD128 existiert
            if not os.path.exists('/dev/dri/renderD128'):
                return False

            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            return 'h264_vaapi' in result.stdout
        except:
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
        if codec == 'hevc' and 'encoder_hevc' in hw_info:
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
        encoder = 'libx265' if codec == 'hevc' else 'libx264'
        return {
            'input_params': [],
            'output_params': [
                '-c:v', encoder,
                '-preset', 'medium',
                '-crf', '23'
            ],
            'encoder': encoder
        }

    def get_hardware_info_string(self):
        """Gibt einen lesbaren String mit Hardware-Informationen zurück"""
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
        return f"{hw_name} (Encoder: {hw_info['encoder']})"

