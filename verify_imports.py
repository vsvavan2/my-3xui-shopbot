import os
import sys
import importlib
import pkgutil

# Add src to path
sys.path.insert(0, os.path.join(os.getcwd(), 'src'))

def check_imports():
    src_dir = os.path.join(os.getcwd(), 'src')
    print(f"Checking imports in {src_dir}...")
    
    error_count = 0
    checked_count = 0
    
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            if file.endswith(".py") and file != "__main__.py":
                # Construct module path
                rel_path = os.path.relpath(os.path.join(root, file), src_dir)
                module_name = rel_path.replace(os.sep, ".")[:-3]
                
                try:
                    importlib.import_module(module_name)
                    print(f"✅ {module_name}")
                    checked_count += 1
                except Exception as e:
                    print(f"❌ {module_name}: {e}")
                    error_count += 1
                    
    print(f"\nChecked {checked_count} modules.")
    if error_count == 0:
        print("🎉 All modules imported successfully!")
    else:
        print(f"⚠️ Found {error_count} import errors.")
        sys.exit(1)

if __name__ == "__main__":
    check_imports()
