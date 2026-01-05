import sys
from pathlib import Path
sys.path.append(str(Path("src").resolve()))

try:
    from shop_bot.bot import handlers
    print("Successfully imported handlers")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
