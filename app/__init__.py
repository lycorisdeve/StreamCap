from .core.runtime.paths import prepare_user_data_dir, resource_dir, user_data_dir
from .initialization.installation_manager import InstallationManager

prepare_user_data_dir()

execute_dir = str(user_data_dir)
resource_dir = str(resource_dir)

__all__ = ["InstallationManager", "execute_dir", "resource_dir"]
