import logging

# Level for success messages. Sits between INFO and WARNING, so a consumer
# can filter out the announcements without losing the outcomes.
SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")
