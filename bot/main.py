import logging

from config import settings
from discord_events import CompBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    CompBot().run(settings.discord_token, log_handler=None)
