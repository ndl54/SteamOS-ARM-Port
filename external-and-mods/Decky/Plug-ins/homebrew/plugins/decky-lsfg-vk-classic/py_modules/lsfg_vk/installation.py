"""
Installation service for lsfg-vk.
"""

import os
import shutil
import traceback
import zipfile
import tempfile
import json
import hashlib
import platform
from pathlib import Path
from typing import Dict, Any

from .base_service import BaseService
from .constants import (
    LIB_FILENAME, JSON_FILENAME, ZIP_FILENAME, BIN_DIR,
    SO_EXT, JSON_EXT, ZIP_LIB_FILENAME, ZIP_JSON_FILENAME, ENABLE_ENV
)
from .config_schema import ConfigurationManager
from .types import InstallationResponse, UninstallationResponse, InstallationCheckResponse


class InstallationService(BaseService):
    """Service for handling lsfg-vk installation and uninstallation"""

    def __init__(self, logger=None):
        super().__init__(logger)

        self.lib_file = self.local_lib_dir / LIB_FILENAME
        self.json_file = self.local_share_dir / JSON_FILENAME

    ARM_LIB = Path("/usr/lib/liblsfg-vk-classic-arm64.so")
    ARM_JSON = Path("/usr/share/vulkan/implicit_layer.d/VkLayer_LS_frame_generation_classic_arm64.json")
    ARCHIVE_SHA256 = "a406b3730144c2011e2c2acd3cf44f3ec6c048ee86099bc9c3ac90aa1515e5ec"

    def _check_arm_artifacts(self):
        if platform.machine().lower() in ("aarch64", "arm64"):
            if not self.ARM_LIB.is_file() or not self.ARM_JSON.is_file():
                raise OSError("Classic ARM64 layer is missing from the image")
            self._validate_manifest(json.loads(self.ARM_JSON.read_text()), arm=True)

    @staticmethod
    def _validate_manifest(data, arm=False):
        layer = data.get("layer", {})
        expected_name = "VK_LAYER_LS_frame_generation_classic" + ("_arm64" if arm else "")
        expected_path = "/usr/lib/liblsfg-vk-classic-arm64.so" if arm else f"../../../lib/{LIB_FILENAME}"
        if (layer.get("name") != expected_name or layer.get("library_path") != expected_path
                or layer.get("enable_environment") != {ENABLE_ENV: "1"}
                or layer.get("disable_environment") != {"DISABLE_LSFG": "1"}):
            raise ValueError("Classic layer manifest is invalid or not isolated")

    def install(self) -> InstallationResponse:
        """Install lsfg-vk by extracting the zip file to ~/.local

        Returns:
            InstallationResponse with success status and message/error
        """
        try:
            plugin_dir = Path(__file__).parent.parent.parent
            zip_path = plugin_dir / BIN_DIR / ZIP_FILENAME

            if not zip_path.exists():
                error_msg = f"{ZIP_FILENAME} not found at {zip_path}"
                self.log.error(error_msg)
                return self._error_response(InstallationResponse, error_msg, message="")

            self._check_arm_artifacts()
            self._assert_launch_script_owned_or_absent()
            # Validate existing settings before publishing any layer files.
            if self.config_file_path.exists():
                ConfigurationManager.parse_toml_content_multi_profile(self.config_file_path.read_text())
            self._ensure_directories()

            self._extract_and_install_files(zip_path)

            self._create_config_file()

            self._create_lsfg_launch_script()

            self.log.info("lsfg-vk installed successfully")
            return self._success_response(InstallationResponse, "lsfg-vk installed successfully")

        except (OSError, zipfile.BadZipFile, shutil.Error) as e:
            error_msg = f"Error installing lsfg-vk: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(InstallationResponse, str(e), message="")
        except Exception as e:
            error_msg = f"Unexpected error installing lsfg-vk: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(InstallationResponse, str(e), message="")

    def _extract_and_install_files(self, zip_path: Path) -> None:
        """Extract zip file and install files to appropriate locations

        Args:
            zip_path: Path to the zip file to extract

        Raises:
            zipfile.BadZipFile: If zip file is corrupted
            OSError: If file operations fail
        """
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() != self.ARCHIVE_SHA256:
            raise ValueError("Classic archive checksum mismatch")
        with zipfile.ZipFile(zip_path) as archive:
            lib = archive.read(f"lib/{ZIP_LIB_FILENAME}")
            manifest = json.loads(archive.read(f"share/vulkan/implicit_layer.d/{ZIP_JSON_FILENAME}"))
        if lib[:6] != b"\x7fELF\x02\x01" or int.from_bytes(lib[18:20], "little") != 62:
            raise ValueError("Classic archive does not contain its x86-64 ELF library")
        layer = manifest.get("layer")
        if not isinstance(layer, dict) or layer.get("library_path") != ZIP_LIB_FILENAME:
            raise ValueError("Unexpected Classic archive manifest")
        layer.update(name="VK_LAYER_LS_frame_generation_classic",
                     library_path=f"../../../lib/{LIB_FILENAME}",
                     enable_environment={ENABLE_ENV: "1"},
                     disable_environment={"DISABLE_LSFG": "1"})
        self._validate_manifest(manifest)
        # Publish the library before its gated manifest. Never install arbitrary
        # archive members or fall back to an ungated upstream manifest.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.local_lib_dir, delete=False) as out:
                temporary = Path(out.name)
                out.write(lib)
                out.flush()
                os.fsync(out.fileno())
            temporary.chmod(0o644)
            os.replace(temporary, self.lib_file)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._write_file(self.json_file, json.dumps(manifest, indent=2) + "\n")

    def _create_config_file(self) -> None:
        """Create or update the TOML config file in ~/.config/lsfg-vk with default configuration and detected DLL path

        If a config file already exists, preserve existing profiles and only update global settings like DLL path.
        """
        if self.config_file_path.exists():
            ConfigurationManager.parse_toml_content_multi_profile(self.config_file_path.read_text())
            return  # Preserve exact user bytes, including comments and DLL choice.
        from .dll_detection import DllDetectionService
        defaults = ConfigurationManager.get_defaults_with_dll_detection(DllDetectionService(self.log))
        self._write_file(self.config_file_path, ConfigurationManager.generate_toml_content(defaults))

    def _create_lsfg_launch_script(self) -> None:
        """Recreate the wrapper from the saved selection, never from defaults."""
        from .configuration import ConfigurationService
        service = ConfigurationService(logger=self.log)
        profiles = ConfigurationManager.parse_toml_content_multi_profile(self.config_file_path.read_text())
        self._write_file(self.lsfg_launch_script_path,
                         service._generate_script_content_for_profile(profiles), 0o755)

    def get_launch_script_path(self) -> str:
        """Get the path to the lsfg launch script

        Returns:
            String path to the launch script file
        """
        return str(self.lsfg_launch_script_path)

    def check_installation(self) -> InstallationCheckResponse:
        """Check if lsfg-vk is already installed

        Returns:
            InstallationCheckResponse with installation status and file paths
        """
        try:
            lib_exists = self.lib_file.is_file()
            json_exists = self.json_file.is_file()
            config_exists = self.config_file_path.is_file()
            script_exists = self.lsfg_launch_script_path.is_file() and os.access(self.lsfg_launch_script_path, os.X_OK)
            self._check_arm_artifacts()
            if json_exists:
                self._validate_manifest(json.loads(self.json_file.read_text()))
            if config_exists:
                ConfigurationManager.parse_toml_content_multi_profile(self.config_file_path.read_text())

            self.log.info(f"Installation check: lib={lib_exists}, json={json_exists}, config={config_exists}")

            return {
                "installed": lib_exists and json_exists and config_exists and script_exists,
                "lib_exists": lib_exists,
                "json_exists": json_exists,
                "script_exists": script_exists,
                "lib_path": str(self.lib_file),
                "json_path": str(self.json_file),
                "script_path": str(self.lsfg_launch_script_path),
                "error": None
            }

        except Exception as e:
            error_msg = f"Error checking lsfg-vk installation: {str(e)}"
            self.log.error(error_msg)
            return {
                "installed": False,
                "lib_exists": False,
                "json_exists": False,
                "script_exists": False,
                "lib_path": str(self.lib_file),
                "json_path": str(self.json_file),
                "script_path": str(self.config_file_path),
                "error": str(e)
            }

    def uninstall(self) -> UninstallationResponse:
        """Uninstall lsfg-vk by removing the installed files

        Note: The config file (conf.toml) is preserved to maintain user's custom profiles

        Returns:
            UninstallationResponse with success status and removed files list
        """
        try:
            self._assert_launch_script_owned_or_absent()
            removed_files = []
            # Remove core lsfg-vk files, but preserve config file to maintain user's custom profiles
            files_to_remove = [self.lib_file, self.json_file, self.lsfg_launch_script_path]

            for file_path in files_to_remove:
                if self._remove_if_exists(file_path):
                    removed_files.append(str(file_path))

            # Also try to remove the old script file if it exists (for backward compatibility)
            if self._remove_if_exists(self.lsfg_script_path):
                removed_files.append(str(self.lsfg_script_path))

            # Don't remove config directory since we're preserving the config file

            if not removed_files:
                return self._success_response(UninstallationResponse,
                                            "No lsfg-vk files found to remove",
                                            removed_files=None)

            self.log.info("lsfg-vk uninstalled successfully")
            return self._success_response(UninstallationResponse,
                                        f"lsfg-vk uninstalled successfully. Removed {len(removed_files)} files.",
                                        removed_files=removed_files)

        except (OSError, ValueError) as e:
            error_msg = f"Error uninstalling lsfg-vk: {str(e)}"
            self.log.error(error_msg)
            return self._error_response(UninstallationResponse, str(e),
                                      message="", removed_files=None)

    def cleanup_on_uninstall(self) -> None:
        """Remove owned files only; preserve user configuration and wrappers."""
        result = self.uninstall()
        if not result["success"]:
            self.log.error(f"Classic uninstall cleanup failed: {result['error']}")
