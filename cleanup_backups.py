import sys
import logging
import asyncio
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.append(str(src_path))

from shop_bot.data_manager import backup_manager, database

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("Starting backup cleanup...")
    
    # Clean backups
    # The backups are stored in 'backups' directory relative to project root
    # DB_FILE is users.db
    
    # Override DB_FILE in database module to ensure we point to the right place if needed
    # But backup_manager uses database.DB_FILE
    
    print(f"Project root: {project_root}")
    print(f"Backups dir: {backup_manager.BACKUPS_DIR}")
    
    deleted_count = backup_manager.delete_all_backups()
    print(f"Deleted {deleted_count} backup files.")
    
    # Also clean up any temporary .db files if they exist
    backups_dir = backup_manager.BACKUPS_DIR
    if backups_dir.exists():
        for f in backups_dir.glob("*.db"):
            try:
                f.unlink()
                print(f"Deleted temp db: {f.name}")
            except Exception as e:
                print(f"Error deleting {f.name}: {e}")

    print("Cleanup complete.")

if __name__ == "__main__":
    main()
