"""
Secure Enclave Key Service (SEKS) - Hardware-bound identity management
Implements TPM 2.0 and Secure Enclave interfaces with graceful fallbacks.
"""

import os
import sys
import hashlib
import json
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import subprocess
import platform

# Add parent directory to path for logger import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import MoltbookLogger

logger = MoltbookLogger("hardware_attestation")

class HardwareType(Enum):
    """Supported hardware security modules"""
    TPM_2_0 = "tpm2"
    APPLE_SECURE_ENCLAVE = "apple_se"
    WINDOWS_HELLO = "windows_hello"
    YUBIKEY_5 = "yubikey5"
    SOFTWARE_EMULATION = "software_fallback"

@dataclass
class HardwareIdentity:
    """Hardware-bound identity data structure"""
    hardware_type: HardwareType
    public_key: str
    attestation_cert: Optional[str] = None
    device_id: Optional[str] = None
    manufacturer: Optional[str] = None
    security_level: int = 0  # 0-100 scale
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firebase-compatible dictionary"""
        return {
            "hardware_type": self.hardware_type.value,
            "public_key": self.public_key,
            "attestation_cert": self.attestation_cert,
            "device_id": self.device_id,
            "manufacturer": self.manufacturer,
            "security_level": self.security_level,
            "timestamp": __import__('datetime').datetime.utcnow().isoformat()
        }

class HardwareAttestationError(Exception):
    """Custom exception for hardware attestation failures"""
    pass

class SecureEnclaveKeyService:
    """Main SEKS implementation with hardware detection and fallback"""
    
    def __init__(self, firestore_client=None):
        self.firestore_client = firestore_client
        self.detected_hardware = None
        self.hardware_identity = None
        self.fallback_activated = False
        
        # Initialize critical state
        self._initialize_hardware_detection()
    
    def _initialize_hardware_detection(self) -> None:
        """Detect available hardware security modules"""
        system = platform.system().lower()
        
        try:
            if system == "darwin":
                self._detect_apple_secure_enclave()
            elif system == "windows":
                self._detect_windows_hello()
            elif system == "linux":
                self._detect_tpm_2_0()
            
            # Always check for Yubikey as it's cross-platform
            self._detect_yubikey()
            
            if not self.detected_hardware:
                logger.warning("No hardware security module detected, using software fallback")
                self.detected_hardware = HardwareType.SOFTWARE_EMULATION
                self.fallback_activated = True
                self.security_level = 40  # Reduced security for software fallback
            else:
                logger.info(f"Detected hardware: {self.detected_hardware.value}")
                
        except Exception as e:
            logger.error(f"Hardware detection failed: {str(e)}")
            self.detected_hardware = HardwareType.SOFTWARE_EMULATION
            self.fallback_activated = True
    
    def _detect_apple_secure_enclave(self) -> bool:
        """Detect Apple Secure Enclave on macOS"""
        try:
            # Check for Secure Enclave via system profiler
            result = subprocess.run(
                ["system_profiler", "SPiBridgeDataType"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if "Apple T2" in result.stdout or "Secure Enclave" in result.stdout:
                self.detected_hardware = HardwareType.APPLE_SECURE_ENCLAVE
                self.security_level = 95
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            pass
        
        return False
    
    def _detect_windows_hello(self) -> bool:
        """Detect Windows Hello biometric authentication"""
        try:
            if os.path.exists("C:\\Windows\\System32\\WindowsHello.dll"):
                # Check for TPM via PowerShell
                result = subprocess.run(
                    ["powershell", "Get-Tpm"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if "TPMPresent" in result.stdout and "True" in result.stdout:
                    self.detected_hardware = HardwareType.WINDOWS_HELLO
                    self.security_level = 90
                    return True
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            pass
        
        return False
    
    def _detect_tpm_2_0(self) -> bool:
        """Detect TPM 2.0 on Linux systems"""
        try:
            # Check TPM device files
            tpm_devices = [
                "/dev/tpm0",
                "/dev/tpmrm0",
                "/sys/class/tpm/tpm0"
            ]
            
            for device in tpm_devices:
                if os.path.exists(device):
                    # Try to use tpm2-tools if available
                    result = subprocess.run(
                        ["tpm2_getcap", "properties-fixed"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        self.detected_hardware = HardwareType.TPM_2_0
                        self.security_level = 92
                        return True
        
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            pass
        
        return False
    
    def _detect_yubikey(self) -> bool:
        """Detect Yubikey 5 via USB"""
        try:
            if platform.system().lower() == "linux":
                result = subprocess.run(
                    ["lsusb"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if "Yubico" in result.stdout:
                    self.detected_hardware = HardwareType.YUBIKEY_5
                    self.security_level = 94
                    return True
            # Windows and macOS detection would require additional logic
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return False
    
    def generate_hardware_identity(self, developer_id: str) -> HardwareIdentity:
        """Generate or retrieve hardware-bound identity"""
        try:
            if self.fallback_activated:
                logger