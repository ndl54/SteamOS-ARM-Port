"""Classic Flatpak is unavailable: its bundled extension IDs collide with v2."""
from .base_service import BaseService


class FlatpakService(BaseService):
    ERROR = ("Frame Gen Classic does not support Flatpak in this image. "
             "Use Decky LSFG-VK 2.0 for Flatpak games.")

    def _unsupported(self, **fields):
        return {"success": False, "error": self.ERROR, "message": "", **fields}

    def get_extension_status(self):
        return self._unsupported(installed_23_08=False, installed_24_08=False, installed_25_08=False)

    def install_extension(self, version):
        return self._unsupported()

    def uninstall_extension(self, version):
        return self._unsupported()

    def get_flatpak_apps(self):
        return self._unsupported(apps=[], total_apps=0)

    def set_app_override(self, app_id):
        return self._unsupported(app_id=app_id, operation="set")

    def remove_app_override(self, app_id):
        return self._unsupported(app_id=app_id, operation="remove")
