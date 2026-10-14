"""Start dispatcher against only the ignored, dedicated development config."""
import os
from pathlib import Path
import sys
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if config.get("ENVIRONMENT")!="development" or not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/"):
    raise SystemExit("Unsafe E2E configuration")
config["PYTHON_DOTENV_DISABLED"]="1"
os.environ.clear(); os.environ.update(config)
sys.path.insert(0,str(ROOT/"backend"))
import bot_dispatcher
if __name__=="__main__":
    bot_dispatcher.main()
