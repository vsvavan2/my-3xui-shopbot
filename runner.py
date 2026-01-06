import os
import sys
import subprocess
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # We are already in the directory or we know where we are relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = script_dir # The script is in the project root
    
    print(f"Target directory: {target_dir}")
    
    os.chdir(target_dir)
    print(f"Changed directory to: {os.getcwd()}")
    print("Files in current directory:")
    for f in os.listdir():
        print(f" - {f}")
    
    print("Files in src:")
    if os.path.exists("src"):
        for f in os.listdir("src"):
            print(f" - {f}")
    else:
        print("src directory not found")

    print("Searching for users.db...")
    db_found = None
    for root, dirs, files in os.walk("."):
        if "users.db" in files:
            db_found = os.path.join(root, "users.db")
            print(f"Found DB at: {db_found}")
            break
    
    if not db_found:
        print("users.db not found in project tree.")

    # Path to venv python
    venv_python = os.path.join(target_dir, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        print(f"Venv python not found at {venv_python}")
        venv_python = sys.executable
    
    print(f"Using python: {venv_python}")

    # Run cleanup_backups.py
    print("-" * 20)
    print("Running cleanup_backups.py...")
    try:
        subprocess.run([venv_python, "cleanup_backups.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running cleanup: {e}")
    except Exception as e:
        print(f"Exception running cleanup: {e}")

    # Run check_db_strings.py
    print("-" * 20)
    print("Running check_db_strings.py...")
    try:
        subprocess.run([venv_python, "check_db_strings.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running db check: {e}")
    except Exception as e:
        print(f"Exception running db check: {e}")

if __name__ == "__main__":
    main()
